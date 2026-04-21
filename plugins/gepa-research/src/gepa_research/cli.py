from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import DISTRIBUTION_NAME, __version__
from .core import (
    add_gate,
    allocate_experiment,
    append_annotation,
    append_infra_event,
    ascii_tree,
    atomic_write_json,
    attempt_dir,
    attempt_log_path,
    attempt_outcome_path,
    attempt_traces_dir,
    best_committed_node,
    collect_gates_from_path,
    compare_scores,
    current_branch,
    delete_discarded_experiment,
    experiment_result_path,
    experiments_dir_for,
    fill_command_template,
    frontier_nodes,
    gepa_research_dir,
    graph_path,
    init_workspace,
    load_annotations,
    load_config,
    load_graph,
    lock_file_for,
    mark_comparison_blocked,
    maybe_commit_worktree,
    node_target_path,
    parse_score,
    path_to_node,
    relative_target,
    remove_gate,
    remove_worktree_only,
    render_git_diff,
    repo_root,
    reset_runtime_state,
    save_config,
    update_node,
    utc_now,
    workspace_path,
)
from .locking import advisory_lock
from .scratchpad import write_scratchpad


app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
gate_app = typer.Typer(no_args_is_help=True)
app.add_typer(gate_app, name="gate")


class Metric(str, Enum):
    max = "max"
    min = "min"


class InstrumentationMode(str, Enum):
    sdk = "sdk"
    inline = "inline"


def _require_workspace(root: Path) -> tuple[dict, dict]:
    config = load_config(root)
    if not config:
        raise RuntimeError("workspace is not initialized; run `uv run gepa-research init ...` first")
    return config, load_graph(root)


def _read_node(root: Path, exp_id: str) -> dict:
    graph = load_graph(root)
    try:
        return graph["nodes"][exp_id]
    except KeyError as exc:
        raise RuntimeError(f"unknown experiment: {exp_id}") from exc


def _resolve_parent_score(graph: dict, parent_id: str) -> float | None:
    if parent_id == "root":
        return None
    parent = graph["nodes"][parent_id]
    return parent.get("score")


def _update_graph_and_write(root: Path, graph: dict) -> None:
    with advisory_lock(lock_file_for(graph_path(root))):
        atomic_write_json(graph_path(root), graph)


def _pick_free_port(preferred: int, max_tries: int = 20) -> int:
    """Find a free TCP port on 127.0.0.1, starting from *preferred* and
    incrementing by 1 on collision. Raises if nothing free in *max_tries*."""
    import socket
    for offset in range(max_tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"no free port in range {preferred}..{preferred + max_tries - 1}"
    )


def _start_dashboard_background(root: Path, port: int = 8080) -> None:
    """Start the dashboard as a background process.

    Probes for a free port starting at *port* (auto-increments on collision),
    writes the actual port to .gepa-research/dashboard.port, and prints a clickable URL.
    """
    pid_file = gepa_research_dir(root) / "dashboard.pid"
    port_file = gepa_research_dir(root) / "dashboard.port"

    # If already running, surface the existing URL instead of starting a second.
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            existing = port_file.read_text().strip() if port_file.exists() else str(port)
            print(f"Dashboard live: http://127.0.0.1:{existing} (pid {pid})")
            return
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    actual_port = _pick_free_port(port)

    env = os.environ.copy()
    env["GEPA_RESEARCH_DASHBOARD_PORT"] = str(actual_port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "gepa_research.dashboard"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    pid_file.write_text(str(proc.pid))
    port_file.write_text(str(actual_port))
    note = "" if actual_port == port else f" (port {port} busy, bumped to {actual_port})"
    print(f"Dashboard live: http://127.0.0.1:{actual_port} (pid {proc.pid}){note}")


def _stop_dashboard(root: Path) -> None:
    """Stop the background dashboard if running."""
    pid_file = gepa_research_dir(root) / "dashboard.pid"
    port_file = gepa_research_dir(root) / "dashboard.port"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 15)  # SIGTERM
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)
    port_file.unlink(missing_ok=True)


def _run_command(command: str, cwd: Path, env: dict[str, str], stdout_path: Path, stderr_path: Path, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if stdout_path == stderr_path:
        combined = (result.stdout or "")
        if result.stderr:
            if combined and not combined.endswith("\n"):
                combined += "\n"
            combined += result.stderr
        stdout_path.write_text(combined, encoding="utf-8")
    else:
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
    return result


def _finalize_result(root: Path, exp_id: str, node: dict, score: float | None, status: str, extra: dict | None = None) -> None:
    payload = {
        "experiment_id": exp_id,
        "score": score,
        "status": status,
        "timestamp": utc_now(),
        "eval_epoch": node.get("eval_epoch"),
    }
    if extra:
        payload.update(extra)
    atomic_write_json(experiment_result_path(root, exp_id), payload)


def _write_attempt_outcome(
    root: Path,
    exp_id: str,
    attempt: int,
    outcome: str,
    *,
    node: dict,
    started_at: str,
    score: float | None = None,
    benchmark: dict | None = None,
    gates: list[dict] | None = None,
    error: str | None = None,
    commit: str | None = None,
    parent_score: float | None = None,
    metric: str | None = None,
) -> None:
    finished = utc_now()
    payload = {
        "experiment_id": exp_id,
        "attempt": attempt,
        "outcome": outcome,
        "hypothesis": node.get("hypothesis"),
        "parent_id": node.get("parent"),
        "parent_score": parent_score,
        "metric": metric,
        "score": score,
        "started_at": started_at,
        "finished_at": finished,
        "benchmark": benchmark,
        "gates": gates or [],
        "error": error,
        "commit": commit,
    }
    atomic_write_json(attempt_outcome_path(root, exp_id, attempt), payload)


def _block_if_epoch_requires_baseline(root: Path, parent_id: str, no_compare: bool) -> None:
    if no_compare:
        return
    config = load_config(root)
    if config.get("comparison_blocked") and parent_id != "root":
        raise RuntimeError("comparison is blocked for the current eval epoch until a new root baseline is committed")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{DISTRIBUTION_NAME} {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """gepa-research CLI."""


@app.command()
def init(
    target: Annotated[str, typer.Option("--target", help="Target file/dir to optimize.")],
    benchmark: Annotated[str, typer.Option("--benchmark", help="Benchmark command template ({worktree}, {target}).")],
    metric: Annotated[Metric, typer.Option("--metric", help="Score direction.")],
    gate: Annotated[Optional[str], typer.Option("--gate", help="Legacy default gate command.")] = None,
    instrumentation_mode: Annotated[
        Optional[InstrumentationMode],
        typer.Option("--instrumentation-mode", help="Tracing style."),
    ] = None,
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8080,
    objective: Annotated[Optional[str], typer.Option("--objective", help="Natural-language goal passed to GEPA's reflection LM.")] = None,
    background: Annotated[Optional[str], typer.Option("--background", help="Domain knowledge / constraints passed to GEPA's reflection LM.")] = None,
    reflection_lm: Annotated[Optional[str], typer.Option("--reflection-lm", help="Default reflection LM (e.g. anthropic/claude-opus-4-7).")] = None,
) -> None:
    root = repo_root()
    run_id = init_workspace(root, target=target, benchmark=benchmark, metric=metric.value, gate=gate)
    if instrumentation_mode:
        meta_file = gepa_research_dir(root) / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["instrumentation_mode"] = instrumentation_mode.value
        atomic_write_json(meta_file, meta)
    if objective or background or reflection_lm:
        cfg = load_config(root)
        if objective:
            cfg["optimization_objective"] = objective
        if background:
            cfg["background"] = background
        if reflection_lm:
            cfg["reflection_lm"] = reflection_lm
        save_config(root, cfg)
    write_scratchpad(root)
    _start_dashboard_background(root, port=port)
    print(f"Initialized gepa-research workspace {run_id} at {workspace_path(root)}")


@app.command()
def new(
    parent: Annotated[str, typer.Option("--parent", help="Parent experiment id (or `root`).")],
    message: Annotated[str, typer.Option("-m", "--message", help="Hypothesis / description.")],
) -> None:
    root = repo_root()
    config, graph = _require_workspace(root)
    if parent not in graph["nodes"]:
        raise RuntimeError(f"unknown parent: {parent}")
    node = allocate_experiment(root, parent_id=parent, hypothesis=message)
    target = node_target_path(root, config, node)
    print(json.dumps({"id": node["id"], "worktree": node["worktree"], "target": str(target)}, indent=2))


@app.command()
def run(
    exp_id: Annotated[str, typer.Argument()],
    timeout: Annotated[int, typer.Option("--timeout", help="Benchmark/gate timeout (seconds).")] = 1800,
) -> None:
    root = repo_root()
    config, graph = _require_workspace(root)
    node = _read_node(root, exp_id)
    if node.get("status") not in (None, "pending", "active", "evaluated", "failed"):
        print(f"ERROR: {exp_id} has status '{node['status']}' -- cannot run again", file=sys.stderr)
        raise typer.Exit(code=1)
    _block_if_epoch_requires_baseline(root, node["parent"], no_compare=False)

    max_attempts = int(config.get("max_attempts", 3))
    evaluated_attempts = int(node.get("evaluated_attempts", 0))
    if evaluated_attempts >= max_attempts:
        print(
            f"ERROR: {exp_id} exhausted {evaluated_attempts}/{max_attempts} attempts. "
            f"Discard with `gepa-research discard {exp_id} --reason \"...\"` or branch elsewhere.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    # Bumped even on failed runs so NNN subdirs never collide.
    attempt_n = int(node.get("current_attempt", 0)) + 1
    started_at = utc_now()

    def _mark_active(current_node: dict, _graph: dict) -> None:
        current_node["status"] = "active"
        current_node["current_attempt"] = attempt_n

    update_node(root, exp_id, _mark_active)

    worktree = Path(node["worktree"])
    target = node_target_path(root, config, node)
    a_dir = attempt_dir(root, exp_id, attempt_n)
    a_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = attempt_traces_dir(root, exp_id, attempt_n)
    traces_dir.mkdir(parents=True, exist_ok=True)
    benchmark_log = a_dir / "benchmark.log"
    benchmark_err = a_dir / "benchmark_err.log"
    metric = config["metric"]
    parent_score = _resolve_parent_score(graph, node["parent"])

    benchmark_cmd = fill_command_template(config["benchmark"], target=target, worktree=worktree)
    env = os.environ.copy()
    env["GEPA_RESEARCH_TRACES_DIR"] = str(traces_dir)
    env["GEPA_RESEARCH_WORKTREE"] = str(worktree)
    env["GEPA_RESEARCH_EXPERIMENT_ID"] = exp_id
    env["GEPA_RESEARCH_ATTEMPT"] = str(attempt_n)

    # Captured before the benchmark runs so it survives crashes too.
    parent_ref = current_branch(root) if node["parent"] == "root" else _read_node(root, node["parent"])["branch"]
    diff_text = render_git_diff(root, parent_ref, worktree, relative_target(config))
    (a_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    gate_records: list[dict] = []
    benchmark_record: dict | None = None

    try:
        try:
            bench = _run_command(benchmark_cmd, cwd=root, env=env, stdout_path=benchmark_log, stderr_path=benchmark_err, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("benchmark_timeout")

        if bench.returncode != 0:
            benchmark_record = {"command": benchmark_cmd, "returncode": bench.returncode, "result": None}
            raise RuntimeError(f"benchmark_exit_{bench.returncode}")

        score, parsed = parse_score(bench.stdout)
        benchmark_record = {"command": benchmark_cmd, "returncode": 0, "result": parsed}

        gate_passed = True
        gate_failures: list[str] = []

        # Collect inherited gates from the tree path (root -> parent)
        inherited_gates = collect_gates_from_path(graph, node["parent"])
        # Also include the legacy --gate from config as an implicit gate
        if config.get("gate"):
            inherited_gates.insert(0, {"name": "_init_gate", "command": config["gate"]})

        gate_origins: dict[str, str] = {}
        for chain_node in path_to_node(graph, node["parent"]):
            for g in chain_node.get("gates", []):
                gate_origins.setdefault(g["name"], chain_node["id"])

        for g in inherited_gates:
            gate_cmd = fill_command_template(g["command"], target=target, worktree=worktree)
            gate_log_file = a_dir / f"gate_{g['name']}.log"
            try:
                gate_result = _run_command(gate_cmd, cwd=root, env=env, stdout_path=gate_log_file, stderr_path=gate_log_file, timeout=timeout)
            except subprocess.TimeoutExpired:
                gate_records.append({
                    "name": g["name"],
                    "from": gate_origins.get(g["name"], "config"),
                    "command": gate_cmd,
                    "passed": False,
                    "returncode": None,
                    "error": "gate_timeout",
                })
                raise RuntimeError(f"gate_timeout:{g['name']}")
            passed = gate_result.returncode == 0
            gate_records.append({
                "name": g["name"],
                "from": gate_origins.get(g["name"], "config"),
                "command": gate_cmd,
                "passed": passed,
                "returncode": gate_result.returncode,
            })
            if not passed:
                gate_failures.append(g["name"])
                gate_passed = False

        if gate_failures:
            print(f"GATE_FAILED {' '.join(gate_failures)}")

        keep = compare_scores(metric, score, parent_score) and gate_passed
        if keep:
            commit = maybe_commit_worktree(node, node.get("hypothesis", "experiment"))

            def _mark_committed(current_node: dict, _graph: dict) -> None:
                current_node["status"] = "committed"
                current_node["score"] = score
                current_node["commit"] = commit
                current_node["benchmark_result"] = parsed
                current_node["gate_result"] = gate_passed
                current_node["gate_failures"] = gate_failures

            update_node(root, exp_id, _mark_committed)
            if config.get("comparison_blocked") and node["parent"] == "root":
                mark_comparison_blocked(root, False)
            _finalize_result(root, exp_id, node, score, "committed", {"commit": commit})
            _write_attempt_outcome(
                root, exp_id, attempt_n, "committed",
                node=node, started_at=started_at, score=score,
                benchmark=benchmark_record, gates=gate_records,
                commit=commit, parent_score=parent_score, metric=metric,
            )
            write_scratchpad(root)
            delta = "" if parent_score is None else f" ({'+' if metric == 'max' else ''}{score - parent_score:.4f} vs parent)"
            print(f"COMMITTED {exp_id} {score}{delta}")
            return

        def _mark_evaluated(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "evaluated"
            current_node["score"] = score
            current_node["benchmark_result"] = parsed
            current_node["gate_result"] = gate_passed
            current_node["gate_failures"] = gate_failures
            current_node["evaluated_attempts"] = int(current_node.get("evaluated_attempts", 0)) + 1

        update_node(root, exp_id, _mark_evaluated)
        _finalize_result(root, exp_id, node, score, "evaluated")
        _write_attempt_outcome(
            root, exp_id, attempt_n, "evaluated",
            node=node, started_at=started_at, score=score,
            benchmark=benchmark_record, gates=gate_records,
            parent_score=parent_score, metric=metric,
        )
        write_scratchpad(root)
        remaining = max_attempts - (evaluated_attempts + 1)
        suffix = f" ({remaining} attempts remaining)" if remaining > 0 else " (no attempts remaining -- retry blocked)"
        reason = []
        if not gate_passed:
            reason.append(f"gate_failed={','.join(gate_failures)}")
        if not compare_scores(metric, score, parent_score):
            reason.append(f"score_regressed (parent={parent_score})")
        print(f"EVALUATED {exp_id} score={score} {' '.join(reason)}{suffix}")
        return
    except Exception as exc:  # noqa: BLE001
        # Try to salvage score from traces written before failure
        salvaged_score = None
        salvaged_result = None
        try:
            trace_files = sorted(traces_dir.glob("*.json"))
            if trace_files:
                task_scores = {}
                for tf in trace_files:
                    t = json.loads(tf.read_text(encoding="utf-8"))
                    task_scores[t["task_id"]] = t.get("score", 0.0)
                if task_scores:
                    salvaged_score = round(sum(task_scores.values()) / len(task_scores), 4)
                    salvaged_result = {"score": salvaged_score, "tasks": task_scores}
        except Exception:
            pass

        error_msg = str(exc)

        def _mark_failed(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "failed"
            current_node["error"] = error_msg
            if salvaged_score is not None:
                current_node["score"] = salvaged_score
                current_node["benchmark_result"] = salvaged_result

        update_node(root, exp_id, _mark_failed)
        _finalize_result(root, exp_id, node, salvaged_score, "failed", {"error": str(exc)})
        _write_attempt_outcome(
            root, exp_id, attempt_n, "failed",
            node=node, started_at=started_at, score=salvaged_score,
            benchmark=benchmark_record, gates=gate_records,
            error=error_msg, parent_score=parent_score, metric=metric,
        )
        write_scratchpad(root)
        print(f"FAILED {exp_id} {exc}")
        raise typer.Exit(code=1)


@app.command()
def done(
    exp_id: Annotated[str, typer.Argument()],
    score: Annotated[float, typer.Option("--score", help="Externally-measured score.")],
    traces: Annotated[Optional[str], typer.Option("--traces", help="Directory of trace files to copy into the experiment.")] = None,
    no_compare: Annotated[bool, typer.Option("--no-compare", help="Skip comparison; mark as failed.")] = False,
) -> None:
    root = repo_root()
    config, graph = _require_workspace(root)
    node = _read_node(root, exp_id)
    if node.get("status") not in (None, "pending", "active", "evaluated", "failed"):
        print(f"ERROR: {exp_id} has status '{node['status']}' -- cannot record again", file=sys.stderr)
        raise typer.Exit(code=1)
    if traces:
        traces_dir = experiments_dir_for(root, exp_id) / "traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        source = Path(traces)
        if source.is_dir():
            for path in source.iterdir():
                if path.is_file():
                    shutil.copy2(path, traces_dir / path.name)
    if no_compare:
        def _mark_failed(current_node: dict, _graph: dict) -> None:
            current_node["status"] = "failed"
            current_node["score"] = score
        update_node(root, exp_id, _mark_failed)
        _finalize_result(root, exp_id, node, score, "failed", {"recorded_only": True})
        write_scratchpad(root)
        print(f"RECORDED {exp_id} score={score} (no compare)")
        return

    _block_if_epoch_requires_baseline(root, node["parent"], no_compare=False)
    parent_score = _resolve_parent_score(graph, node["parent"])
    metric = config["metric"]
    keep = compare_scores(metric, score, parent_score)
    if config.get("comparison_blocked") and node["parent"] == "root":
        mark_comparison_blocked(root, False)
    status = "committed" if keep else "evaluated"

    def _mark(current_node: dict, _graph: dict) -> None:
        current_node["status"] = status
        current_node["score"] = score
        if status == "evaluated":
            current_node["evaluated_attempts"] = int(current_node.get("evaluated_attempts", 0)) + 1

    update_node(root, exp_id, _mark)
    _finalize_result(root, exp_id, node, score, status, {"recorded_only": True})
    write_scratchpad(root)
    print(f"{status.upper()} {exp_id} {score}")


@app.command()
def discard(
    exp_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason", help="Why discarded.")],
) -> None:
    root = repo_root()
    node = _read_node(root, exp_id)

    def _mark(current_node: dict, _graph: dict) -> None:
        current_node["status"] = "discarded"
        current_node["discard_reason"] = reason

    update_node(root, exp_id, _mark)
    _finalize_result(root, exp_id, node, node.get("score"), "discarded", {"reason": reason})
    delete_discarded_experiment(root, node)
    write_scratchpad(root)
    print(f"DISCARDED {exp_id}: {reason}")


@app.command()
def prune(
    exp_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason", help="Why pruned.")],
) -> None:
    root = repo_root()

    def _mark(current_node: dict, _graph: dict) -> None:
        if current_node.get("status") != "committed":
            raise RuntimeError("only committed nodes can be pruned")
        current_node["status"] = "pruned"
        current_node["pruned_reason"] = reason

    update_node(root, exp_id, _mark)
    write_scratchpad(root)
    print(f"PRUNED {exp_id}: {reason}")


@app.command()
def gc() -> None:
    root = repo_root()
    graph = load_graph(root)
    removed = []
    for node in graph["nodes"].values():
        if node["id"] == "root":
            continue
        if node.get("status") not in {"committed", "failed", "pruned"}:
            continue
        children = [graph["nodes"][cid] for cid in node.get("children", []) if cid in graph["nodes"]]
        if any(child.get("status") == "active" for child in children):
            continue
        worktree = Path(node["worktree"])
        if worktree.exists():
            remove_worktree_only(root, node)
            removed.append(node["id"])
    print(json.dumps({"removed": removed}, indent=2))


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", help="Confirm destructive reset.")] = False,
) -> None:
    if not yes:
        raise RuntimeError("reset is destructive; re-run with --yes")
    root = repo_root()
    _stop_dashboard(root)
    reset_runtime_state(root)
    print("Reset gepa-research runtime state")


@app.command()
def status() -> None:
    root = repo_root()
    config, graph = _require_workspace(root)
    metric = config["metric"]
    nodes = [node for node in graph["nodes"].values() if node["id"] != "root"]
    committed = [node for node in nodes if node.get("status") == "committed"]
    best = None
    if committed:
        scores = [float(node["score"]) for node in committed if node.get("score") is not None]
        best = max(scores) if metric == "max" else min(scores)
    print(
        f"metric={metric} epoch={config.get('current_eval_epoch', 1)} "
        f"experiments={len(nodes)} committed={sum(1 for n in nodes if n.get('status') == 'committed')} "
        f"evaluated={sum(1 for n in nodes if n.get('status') == 'evaluated')} "
        f"discarded={sum(1 for n in nodes if n.get('status') == 'discarded')} "
        f"failed={sum(1 for n in nodes if n.get('status') == 'failed')} "
        f"active={sum(1 for n in nodes if n.get('status') == 'active')} best={best}"
    )


@app.command()
def tree() -> None:
    root = repo_root()
    config, graph = _require_workspace(root)
    print(ascii_tree(graph, config["metric"]))


@app.command()
def frontier() -> None:
    root = repo_root()
    _config, graph = _require_workspace(root)
    nodes = [
        {
            "id": node["id"],
            "score": node.get("score"),
            "epoch": node.get("eval_epoch"),
            "hypothesis": node.get("hypothesis"),
        }
        for node in frontier_nodes(graph)
    ]
    print(json.dumps(nodes, indent=2))


@app.command()
def scratchpad() -> None:
    root = repo_root()
    print(write_scratchpad(root))


@app.command()
def get(
    exp_id: Annotated[str, typer.Argument()],
    filename: Annotated[Optional[str], typer.Argument()] = None,
) -> None:
    root = repo_root()
    if filename:
        path = experiments_dir_for(root, exp_id) / filename
        print(path.read_text(encoding="utf-8"))
        return
    graph = load_graph(root)
    if exp_id not in graph["nodes"]:
        raise RuntimeError(f"unknown experiment: {exp_id}")
    node = dict(graph["nodes"][exp_id])
    node["own_gates"] = node.get("gates", [])
    node["gates"] = collect_gates_from_path(graph, exp_id)
    print(json.dumps(node, indent=2))


@app.command()
def path(
    exp_id: Annotated[str, typer.Argument()],
) -> None:
    root = repo_root()
    _config, graph = _require_workspace(root)
    if exp_id not in graph["nodes"]:
        raise RuntimeError(f"unknown experiment: {exp_id}")
    chain = path_to_node(graph, exp_id)
    for node in chain:
        score_str = f"  score={node['score']}" if node.get("score") is not None else ""
        hyp = f"  {node.get('hypothesis', '')}" if node["id"] != "root" else ""
        prefix = "  -> " if node["id"] != "root" else ""
        print(f"{prefix}{node['id']}{score_str}{hyp}")


@app.command()
def diff(
    exp_id: Annotated[str, typer.Argument()],
    other_id: Annotated[Optional[str], typer.Argument()] = None,
) -> None:
    root = repo_root()
    if other_id is None:
        node = _read_node(root, exp_id)
        attempt = int(node.get("current_attempt", 0))
        if attempt == 0:
            print("")
            return
        target = attempt_log_path(root, exp_id, attempt, "diff.patch")
        print(target.read_text(encoding="utf-8") if target.exists() else "")
        return
    config, graph = _require_workspace(root)
    node_a = _read_node(root, exp_id)
    node_b = _read_node(root, other_id)
    ref_a = node_a.get("commit") or node_a.get("branch")
    ref_b = node_b.get("commit") or node_b.get("branch")
    if not ref_a or not ref_b:
        raise RuntimeError("both experiments must have a commit or branch to diff")
    result = subprocess.run(
        ["git", "diff", ref_a, ref_b, "--", relative_target(config)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    print(result.stdout)


@app.command()
def traces(
    exp_id: Annotated[str, typer.Argument()],
    task: Annotated[Optional[str], typer.Argument()] = None,
) -> None:
    root = repo_root()
    node = _read_node(root, exp_id)
    attempt = int(node.get("current_attempt", 0))
    if attempt == 0:
        if task:
            print("")
        else:
            print("{}")
        return
    traces_dir = attempt_traces_dir(root, exp_id, attempt)
    if task:
        path = traces_dir / f"task_{task}.json"
        print(path.read_text(encoding="utf-8"))
        return
    payload = {}
    if traces_dir.exists():
        for path in sorted(traces_dir.glob("*.json")):
            payload[path.name] = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(payload, indent=2))


@app.command()
def annotate(
    exp_id: Annotated[str, typer.Argument()],
    analysis: Annotated[str, typer.Argument()],
    task: Annotated[Optional[str], typer.Option("--task", help="Task id the analysis refers to.")] = None,
) -> None:
    root = repo_root()
    entry = append_annotation(root, exp_id, task, analysis)
    write_scratchpad(root)
    print(json.dumps(entry, indent=2))


@app.command()
def annotations(
    task: Annotated[Optional[str], typer.Option("--task", help="Filter by task id.")] = None,
    exp: Annotated[Optional[str], typer.Option("--exp", help="Filter by experiment id.")] = None,
) -> None:
    root = repo_root()
    entries = load_annotations(root).get("annotations", [])
    if task:
        entries = [entry for entry in entries if entry.get("task_id") == task]
    if exp:
        entries = [entry for entry in entries if entry.get("experiment_id") == exp]
    print(json.dumps(entries, indent=2))


@app.command()
def log(
    exp_id: Annotated[str, typer.Argument()],
    filename: Annotated[str, typer.Argument()],
) -> None:
    root = repo_root()
    payload = sys.stdin.read()
    target = experiments_dir_for(root, exp_id) / filename
    target.write_text(payload, encoding="utf-8")
    print(str(target))


@app.command("set")
def set_cmd(
    exp_id: Annotated[str, typer.Argument()],
    tag: Annotated[Optional[str], typer.Option("--tag", help="Tag to add.")] = None,
    note: Annotated[Optional[str], typer.Option("--note", help="Note to append.")] = None,
) -> None:
    root = repo_root()

    def _mutate(current_node: dict, _graph: dict) -> None:
        current_node.setdefault("tags", [])
        current_node.setdefault("notes", [])
        if tag:
            if tag not in current_node["tags"]:
                current_node["tags"].append(tag)
        if note:
            current_node["notes"].append({"text": note, "timestamp": utc_now()})

    node = update_node(root, exp_id, _mutate)
    write_scratchpad(root)
    print(json.dumps(node, indent=2))


@app.command()
def infra(
    message: Annotated[str, typer.Option("-m", "--message", help="Event description.")],
    breaking: Annotated[bool, typer.Option("--breaking", help="Bump eval epoch and block comparison.")] = False,
) -> None:
    root = repo_root()
    event = append_infra_event(root, message, breaking)
    if breaking:
        config = load_config(root)
        config["current_eval_epoch"] = int(config.get("current_eval_epoch", 1)) + 1
        config["comparison_blocked"] = True
        save_config(root, config)
    write_scratchpad(root)
    print(json.dumps(event, indent=2))


@gate_app.command("add")
def gate_add_cmd(
    exp_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Option("--name", help="Gate identifier.")],
    command: Annotated[str, typer.Option("--command", help="Gate command (returns 0 = pass).")],
) -> None:
    root = repo_root()
    _require_workspace(root)
    entry = add_gate(root, exp_id, name, command)
    write_scratchpad(root)
    print(json.dumps(entry, indent=2))


@gate_app.command("list")
def gate_list_cmd(
    exp_id: Annotated[str, typer.Argument()],
) -> None:
    root = repo_root()
    _config, graph = _require_workspace(root)
    gates = collect_gates_from_path(graph, exp_id)
    node_gates_map: dict[str, str] = {}
    for node in path_to_node(graph, exp_id):
        for g in node.get("gates", []):
            node_gates_map[g["name"]] = node["id"]
    output = []
    for g in gates:
        output.append({
            "name": g["name"],
            "command": g["command"],
            "from": node_gates_map.get(g["name"], "unknown"),
        })
    print(json.dumps(output, indent=2))


@gate_app.command("remove")
def gate_remove_cmd(
    exp_id: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Option("--name", help="Gate to remove.")],
) -> None:
    root = repo_root()
    _require_workspace(root)
    remove_gate(root, exp_id, name)
    write_scratchpad(root)
    print(f"Removed gate '{name}' from {exp_id}")


@app.command()
def optimize(
    max_metric_calls: Annotated[int, typer.Option("--max-metric-calls", help="GEPA evaluator-call budget.")] = 50,
    stall: Annotated[int, typer.Option("--stall", help="Consecutive iterations without improvement before auto-stop.")] = 5,
    reflection_lm: Annotated[Optional[str], typer.Option("--reflection-lm")] = None,
    objective: Annotated[Optional[str], typer.Option("--objective")] = None,
    background: Annotated[Optional[str], typer.Option("--background")] = None,
) -> None:
    from .gepa_adapter import run_gepa_optimize

    root = repo_root()
    config, graph = _require_workspace(root)
    metric = config["metric"]

    best = best_committed_node(graph, metric)
    if best is None:
        print(
            "ERROR: no committed node to seed from. Run `/discover` first to commit a baseline.",
            file=sys.stderr,
        )
        raise typer.Exit(code=1)

    parent_id = best["id"]

    print(
        f"gepa-research optimize: seed={parent_id} score={best.get('score')} "
        f"max-metric-calls={max_metric_calls} stall={stall}"
    )

    result = run_gepa_optimize(
        root,
        parent_id=parent_id,
        max_metric_calls=max_metric_calls,
        stall=stall,
        reflection_lm=reflection_lm,
        objective=objective,
        background=background,
    )

    summary: dict[str, object] = {
        "best_candidate_idx": getattr(result, "best_idx", None),
        "num_candidates": len(getattr(result, "candidates", []) or []),
        "total_metric_calls": getattr(result, "total_metric_calls", None),
    }
    try:
        best_score = max(getattr(result, "val_aggregate_scores", []) or [float("nan")])
        summary["best_aggregate_score"] = best_score
    except (TypeError, ValueError):
        pass
    print(json.dumps(summary, indent=2, default=str))


@app.command()
def dashboard(
    port: Annotated[int, typer.Option("--port", help="Dashboard port.")] = 8080,
) -> None:
    from .dashboard import create_app

    root = repo_root()
    actual_port = _pick_free_port(port)
    (gepa_research_dir(root) / "dashboard.port").write_text(str(actual_port))
    note = "" if actual_port == port else f" (port {port} busy, bumped to {actual_port})"
    print(f"Dashboard live: http://127.0.0.1:{actual_port}{note}", flush=True)
    flask_app = create_app(root)
    flask_app.run(host="127.0.0.1", port=actual_port, debug=False)


def main(argv: list[str] | None = None) -> None:
    try:
        app(args=argv, standalone_mode=False)
    except (typer.Exit, SystemExit) as exc:
        code = exc.exit_code if isinstance(exc, typer.Exit) else (exc.code or 0)
        sys.exit(code if isinstance(code, int) else 0)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
