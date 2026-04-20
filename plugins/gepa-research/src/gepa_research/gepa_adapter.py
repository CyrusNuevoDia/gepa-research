"""Bridge between gepa's evaluator protocol and gepa-research's worktree/benchmark machinery.

The core loop mirrors `cli.cmd_run`: allocate a worktree, write the candidate
files, run the benchmark, run inherited gates, score. The result is backported
into graph.json as a node so the dashboard and the rest of the CLI keep
working unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .core import (
    allocate_experiment,
    atomic_write_json,
    attempt_dir,
    attempt_traces_dir,
    collect_gates_from_path,
    compare_scores,
    fill_command_template,
    load_config,
    load_graph,
    load_json,
    lock_file_for,
    maybe_commit_worktree,
    node_target_path,
    parse_score,
    relative_target,
    resolve_parent_score,
    update_node,
    workspace_path,
)
from .locking import advisory_lock


_DEFAULT_BENCHMARK_TIMEOUT = 900  # seconds; per-candidate


def _write_candidate(worktree: Path, candidate: dict[str, str], target_relpath: str) -> None:
    """Apply a candidate dict to files in the worktree.

    Keys are paths relative to the worktree. In single-target mode the
    candidate dict has one key matching `target_relpath`; in multi-target mode
    every key is written as-is.
    """
    for relpath, contents in candidate.items():
        dest = worktree / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(contents, encoding="utf-8")
    # If the candidate is in gepa's single-string mode it arrives as
    # {"current_candidate": "..."} — map that onto the declared target file.
    if "current_candidate" in candidate and target_relpath not in candidate:
        dest = worktree / target_relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(candidate["current_candidate"], encoding="utf-8")


def _run_subprocess(command: str, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class GepaResearchAdapter:
    """Evaluator callable for ``gepa.optimize_anything``.

    Each ``evaluate`` call allocates a fresh experiment node (and worktree)
    off the configured parent, writes the candidate, runs the benchmark and
    gates, commits on success. Returns ``(score, side_info)`` so gepa can
    reflect on failures.
    """

    def __init__(
        self,
        root: Path,
        *,
        parent_id: str,
        benchmark_timeout: int = _DEFAULT_BENCHMARK_TIMEOUT,
    ) -> None:
        self._root = root
        self._parent_id = parent_id
        self._benchmark_timeout = benchmark_timeout

    def evaluate(self, candidate: Any, example: Any = None) -> tuple[float, dict[str, Any]]:
        config = load_config(self._root)
        metric = config["metric"]
        target_relpath = relative_target(config)

        # gepa hands us a dict (or a str in single-param mode, which
        # optimize_anything normalizes to {"current_candidate": str}).
        if isinstance(candidate, str):
            candidate = {"current_candidate": candidate}

        hypothesis = "gepa candidate"
        if isinstance(example, dict):
            hypothesis = example.get("hypothesis", hypothesis)

        node = allocate_experiment(self._root, parent_id=self._parent_id, hypothesis=hypothesis)
        exp_id = node["id"]
        worktree = Path(node["worktree"])
        target = node_target_path(self._root, config, node)

        side_info: dict[str, Any] = {"experiment_id": exp_id}

        try:
            _write_candidate(worktree, candidate, target_relpath)
        except Exception as exc:  # noqa: BLE001
            side_info["error"] = f"apply_candidate_failed: {exc}"
            self._mark_failed(exp_id, score=0.0, error=side_info["error"])
            return 0.0, side_info

        attempt_n = 1

        def _mark_active(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "active"
            current_node["current_attempt"] = attempt_n

        update_node(self._root, exp_id, _mark_active)

        a_dir = attempt_dir(self._root, exp_id, attempt_n)
        a_dir.mkdir(parents=True, exist_ok=True)
        traces_dir = attempt_traces_dir(self._root, exp_id, attempt_n)
        traces_dir.mkdir(parents=True, exist_ok=True)

        benchmark_cmd = fill_command_template(config["benchmark"], target=target, worktree=worktree)
        env = os.environ.copy()
        env["GEPA_RESEARCH_TRACES_DIR"] = str(traces_dir)
        env["GEPA_RESEARCH_WORKTREE"] = str(worktree)
        env["GEPA_RESEARCH_EXPERIMENT_ID"] = exp_id
        env["GEPA_RESEARCH_ATTEMPT"] = str(attempt_n)

        try:
            bench = _run_subprocess(benchmark_cmd, cwd=self._root, env=env, timeout=self._benchmark_timeout)
        except subprocess.TimeoutExpired:
            side_info["error"] = "benchmark_timeout"
            side_info["stderr"] = ""
            self._mark_failed(exp_id, score=0.0, error="benchmark_timeout")
            return 0.0, side_info

        side_info["stdout"] = bench.stdout[-4000:] if bench.stdout else ""
        side_info["stderr"] = bench.stderr[-4000:] if bench.stderr else ""

        if bench.returncode != 0:
            side_info["error"] = f"benchmark_exit_{bench.returncode}"
            self._mark_failed(exp_id, score=0.0, error=side_info["error"])
            return 0.0, side_info

        try:
            score, parsed = parse_score(bench.stdout)
        except ValueError as exc:
            side_info["error"] = f"parse_score_failed: {exc}"
            self._mark_failed(exp_id, score=0.0, error=side_info["error"])
            return 0.0, side_info

        side_info["benchmark_result"] = parsed

        # Inherited gates (+ legacy config["gate"])
        graph = load_graph(self._root)
        inherited_gates = collect_gates_from_path(graph, self._parent_id)
        if config.get("gate"):
            inherited_gates.insert(0, {"name": "_init_gate", "command": config["gate"]})

        gate_failures: list[str] = []
        for g in inherited_gates:
            gate_cmd = fill_command_template(g["command"], target=target, worktree=worktree)
            try:
                gate_result = _run_subprocess(gate_cmd, cwd=self._root, env=env, timeout=self._benchmark_timeout)
            except subprocess.TimeoutExpired:
                gate_failures.append(f"{g['name']}:timeout")
                continue
            if gate_result.returncode != 0:
                gate_failures.append(g["name"])

        if gate_failures:
            side_info["gate_failures"] = gate_failures
            self._mark_evaluated(exp_id, score=score, gate_passed=False, gate_failures=gate_failures, parsed=parsed)
            return 0.0, side_info

        # Per-task traces as compact side info for gepa's reflector.
        task_traces: list[dict[str, Any]] = []
        try:
            for tf in sorted(traces_dir.glob("task_*.json")):
                task_traces.append(json.loads(tf.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
        if task_traces:
            side_info["task_traces"] = task_traces

        parent_score = resolve_parent_score(graph, self._parent_id)
        keep = compare_scores(metric, score, parent_score)
        if keep:
            commit = maybe_commit_worktree(node, node.get("hypothesis", hypothesis))

            def _mark_committed(current_node: dict, _graph: dict) -> None:
                current_node["status"] = "committed"
                current_node["score"] = score
                current_node["commit"] = commit
                current_node["benchmark_result"] = parsed
                current_node["gate_result"] = True

            update_node(self._root, exp_id, _mark_committed)
        else:
            self._mark_evaluated(exp_id, score=score, gate_passed=True, gate_failures=[], parsed=parsed)

        return score, side_info

    def _mark_evaluated(
        self, exp_id: str, *, score: float, gate_passed: bool, gate_failures: list[str], parsed: Any
    ) -> None:
        def _mutate(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "evaluated"
            current_node["score"] = score
            current_node["benchmark_result"] = parsed
            current_node["gate_result"] = gate_passed
            current_node["gate_failures"] = gate_failures
            current_node["evaluated_attempts"] = int(current_node.get("evaluated_attempts", 0)) + 1

        update_node(self._root, exp_id, _mutate)

    def _mark_failed(self, exp_id: str, *, score: float, error: str) -> None:
        def _mutate(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "failed"
            current_node["error"] = error
            current_node["score"] = score

        update_node(self._root, exp_id, _mutate)


def build_seed_candidate(root: Path, parent_id: str) -> dict[str, str]:
    """Read the target file from the parent's worktree and return it as a
    single-key candidate dict keyed by the relative target path.

    This keeps the candidate dict's key aligned with the path `_write_candidate`
    will write back to.
    """
    config = load_config(root)
    graph = load_graph(root)
    nodes = graph["nodes"]
    if parent_id not in nodes:
        raise KeyError(f"unknown parent: {parent_id}")

    rel = relative_target(config)
    parent = nodes[parent_id]
    if parent_id == "root" or not parent.get("worktree"):
        source = root / rel
    else:
        source = Path(parent["worktree"]) / rel
    if not source.exists():
        raise FileNotFoundError(f"target file not found at {source}")
    return {rel: source.read_text(encoding="utf-8")}


PROGRESS_FILE = "progress.json"


def progress_path(root: Path) -> Path:
    return workspace_path(root) / PROGRESS_FILE


def _write_progress(root: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge *updates* into progress.json under the graph-file lock.

    Thread-safe: multiple callback threads can call this concurrently.
    """
    path = progress_path(root)
    with advisory_lock(lock_file_for(path)):
        current = load_json(path, {})
        current.update(updates)
        atomic_write_json(path, current)
        return current


class GEPAProgressCallback:
    """Write progress snapshots to ``.gepa-research/<run>/progress.json`` after
    each GEPA event so the dashboard can show budget + stall + best-candidate
    state live.

    Safe under ``num_parallel_proposals > 1`` because all writes are serialized
    through :func:`_write_progress`.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_metric_calls: int,
        stall_limit: int,
        num_parallel_proposals: int,
    ) -> None:
        self._root = root
        self._lock = threading.Lock()
        self._stall_counter = 0
        self._max = max_metric_calls
        self._stall_limit = stall_limit
        self._num_parallel = num_parallel_proposals

    def on_optimization_start(self, event: dict) -> None:
        _write_progress(
            self._root,
            {
                "status": "running",
                "max_metric_calls": self._max,
                "stall_limit": self._stall_limit,
                "num_parallel_proposals": self._num_parallel,
                "metric_calls_used": 0,
                "iterations_without_improvement": 0,
                "best_candidate_idx": None,
                "total_iterations": 0,
            },
        )

    def on_iteration_end(self, event: dict) -> None:
        with self._lock:
            if event.get("proposal_accepted"):
                self._stall_counter = 0
            else:
                self._stall_counter += 1
            snapshot = {
                "total_iterations": event.get("iteration"),
                "iterations_without_improvement": self._stall_counter,
            }
        _write_progress(self._root, snapshot)

    def on_budget_updated(self, event: dict) -> None:
        used = event.get("metric_calls_used")
        if used is None:
            return
        _write_progress(self._root, {"metric_calls_used": used})

    def on_optimization_end(self, event: dict) -> None:
        _write_progress(
            self._root,
            {
                "status": "done",
                "best_candidate_idx": event.get("best_candidate_idx"),
                "total_iterations": event.get("total_iterations"),
                "metric_calls_used": event.get("total_metric_calls"),
            },
        )

    def on_error(self, event: dict) -> None:
        # Don't flip status to "error" for per-iteration exceptions that GEPA
        # logs but continues past. Just surface the last message.
        exc = event.get("exception")
        _write_progress(self._root, {"last_error": str(exc) if exc else None})


def run_gepa_optimize(
    root: Path,
    *,
    parent_id: str,
    max_metric_calls: int = 50,
    stall: int = 5,
    num_parallel_proposals: int = 1,
    objective: str | None = None,
    background: str | None = None,
    reflection_lm: str | None = None,
) -> Any:
    """Hand the current workspace to ``gepa.optimize_anything`` and return the
    ``GEPAResult``.  All candidate evaluation, worktree allocation, and graph
    backporting is handled by :class:`GepaResearchAdapter`.

    ``num_parallel_proposals`` > 1 runs N independent evaluate→propose→evaluate
    pipelines concurrently per iteration (GEPA's built-in thread pool). Each
    ``adapter.evaluate`` call allocates its own git worktree, and all
    ``graph.json`` / ``progress.json`` writes are serialized via file locks.
    """
    # Imported lazily so the top-level module loads without gepa installed.
    from gepa.optimize_anything import (
        EngineConfig,
        GEPAConfig,
        ReflectionConfig,
        optimize_anything,
    )
    from gepa.utils.stop_condition import (
        CompositeStopper,
        MaxMetricCallsStopper,
        NoImprovementStopper,
    )

    config = load_config(root)
    if not config:
        raise RuntimeError("workspace is not initialized; run `gepa-research init ...` first")

    seed = build_seed_candidate(root, parent_id)
    adapter = GepaResearchAdapter(root, parent_id=parent_id)

    engine_kwargs: dict[str, Any] = {
        "max_metric_calls": max_metric_calls,
        "display_progress_bar": False,
        "parallel": True,
        "num_parallel_proposals": num_parallel_proposals,
    }
    reflection_kwargs: dict[str, Any] = {}
    if reflection_lm:
        reflection_kwargs["reflection_lm"] = reflection_lm

    gepa_config = GEPAConfig(
        engine=EngineConfig(**engine_kwargs),
        reflection=ReflectionConfig(**reflection_kwargs) if reflection_kwargs else ReflectionConfig(),
        stop_callbacks=CompositeStopper(
            MaxMetricCallsStopper(max_metric_calls=max_metric_calls),
            NoImprovementStopper(max_iterations_without_improvement=stall),
        ),
        callbacks=[
            GEPAProgressCallback(
                root,
                max_metric_calls=max_metric_calls,
                stall_limit=stall,
                num_parallel_proposals=num_parallel_proposals,
            )
        ],
    )

    return optimize_anything(
        seed_candidate=seed,
        evaluator=adapter.evaluate,
        objective=objective or config.get("optimization_objective"),
        background=background or config.get("background"),
        config=gepa_config,
    )
