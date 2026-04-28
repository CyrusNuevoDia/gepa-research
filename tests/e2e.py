from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "gepa-research"


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)
    return result


def gepa_research(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["uv", "run", "--project", str(PLUGIN_ROOT), "gepa-research", *args], cwd=cwd, check=check)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_repo(root: Path) -> None:
    run(["git", "init", "-b", "main"], cwd=root)
    run(["git", "config", "user.name", "gepa-research"], cwd=root)
    run(["git", "config", "user.email", "gepa-research@example.com"], cwd=root)


def setup_max_repo(root: Path) -> None:
    write(
        root / "agent.py",
        'STATE = "baseline"\n',
    )
    write(
        root / "eval.py",
        """from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
score = 1.0 if "GOOD" in content else 0.0
traces_dir = os.environ.get("GEPA_RESEARCH_TRACES_DIR")
if traces_dir:
    Path(traces_dir).mkdir(parents=True, exist_ok=True)
    Path(traces_dir, "task_0.json").write_text(json.dumps({
        "experiment_id": "external",
        "task_id": "0",
        "status": "passed" if score > 0 else "failed",
        "score": score
    }, indent=2), encoding="utf-8")
print(json.dumps({"score": score, "tasks": {"0": score}}))
""",
    )
    write(
        root / "gate.py",
        """from __future__ import annotations
import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
sys.exit(1 if "FORBIDDEN" in content else 0)
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: max"], cwd=root)


def setup_min_repo(root: Path) -> None:
    write(
        root / "agent.py",
        'STATE = "baseline"\n',
    )
    write(
        root / "eval.py",
        """from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
score = 5.0 if "BETTER" in content else 10.0
print(json.dumps({"score": score, "tasks": {"0": score}}))
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: min"], cwd=root)


def load_graph(root: Path) -> dict:
    return json.loads((root / ".gepa-research" / "run_0000" / "graph.json").read_text(encoding="utf-8"))


def load_outcome(root: Path, exp_id: str, attempt: int) -> dict:
    path = root / ".gepa-research" / "run_0000" / "experiments" / exp_id / "attempts" / f"{attempt:03d}" / "outcome.json"
    return json.loads(path.read_text(encoding="utf-8"))


def parse_last_json_blob(text: str) -> dict:
    start = text.rfind("{")
    if start == -1:
        raise ValueError(f"No JSON object found in output: {text!r}")
    return json.loads(text[start:])


def test_max_flow(root: Path) -> None:
    gepa_research(
        [
            "init",
            "--target",
            "agent.py",
            "--benchmark",
            "python eval.py --agent {target}",
            "--gate",
            "python gate.py --agent {target}",
            "--metric",
            "max",
        ],
        cwd=root,
    )
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    baseline = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 0.0" in baseline.stdout

    gepa_research(["new", "--parent", "exp_0000", "-m", "make it good"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0001" / "agent.py", 'STATE = "GOOD"\n')
    improved = gepa_research(["run", "exp_0001"], cwd=root)
    assert "COMMITTED exp_0001 1.0" in improved.stdout

    gepa_research(["new", "--parent", "exp_0001", "-m", "break the gate"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0002" / "agent.py", 'STATE = "GOOD FORBIDDEN"\n')
    gated = gepa_research(["run", "exp_0002"], cwd=root)
    assert "EVALUATED exp_0002" in gated.stdout
    assert "gate_failed" in gated.stdout

    # Gate-failing node stays evaluated with worktree + branch intact for retry.
    assert (root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0002").exists()
    branches = run(["git", "branch", "--list", "gepa-research/run_0000/exp_0002"], cwd=root).stdout.strip()
    assert branches, "branch should persist on evaluated outcome"

    gepa_research(["annotate", "exp_0002", "0", "gate failure"], cwd=root)

    # Explicit discard cleans up both worktree and branch.
    gepa_research(["discard", "exp_0002", "--reason", "abandon hypothesis"], cwd=root)
    assert not (root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0002").exists()
    branches = run(["git", "branch", "--list", "gepa-research/run_0000/exp_0002"], cwd=root).stdout.strip()
    assert not branches
    # Per-attempt artifacts preserved for forensics.
    assert (root / ".gepa-research" / "run_0000" / "experiments" / "exp_0002" / "attempts" / "001" / "outcome.json").exists()

    gepa_research(["prune", "exp_0000", "--reason", "dominated"], cwd=root)

    graph = load_graph(root)
    assert graph["nodes"]["exp_0000"]["status"] == "pruned"
    assert graph["nodes"]["exp_0001"]["status"] == "committed"
    assert graph["nodes"]["exp_0002"]["status"] == "discarded"
    frontier = json.loads(gepa_research(["frontier"], cwd=root).stdout)
    assert [node["id"] for node in frontier] == ["exp_0001"]

    gepa_research(["reset", "--yes"], cwd=root)
    assert not (root / ".gepa-research" / "run_0000").exists()
    branches = run(["git", "branch", "--list", "gepa-research/*"], cwd=root).stdout.strip()
    assert not branches


def test_min_flow(root: Path) -> None:
    gepa_research(
        [
            "init",
            "--target",
            "agent.py",
            "--benchmark",
            "python eval.py --agent {target}",
            "--metric",
            "min",
        ],
        cwd=root,
    )
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    baseline = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 10.0" in baseline.stdout

    gepa_research(["new", "--parent", "exp_0000", "-m", "lower score"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0001" / "agent.py", 'STATE = "BETTER"\n')
    improved = gepa_research(["run", "exp_0001"], cwd=root)
    assert "COMMITTED exp_0001 5.0" in improved.stdout

    graph = load_graph(root)
    assert graph["nodes"]["exp_0001"]["score"] == 5.0
    status = gepa_research(["status"], cwd=root).stdout
    assert "metric=min" in status
    assert "best=5.0" in status


def test_stale_branch_recovery(root: Path) -> None:
    gepa_research(
        [
            "init",
            "--target",
            "agent.py",
            "--benchmark",
            "python eval.py --agent {target}",
            "--metric",
            "max",
        ],
        cwd=root,
    )
    run(["git", "branch", "gepa-research/exp_0000"], cwd=root)
    created = gepa_research(["new", "--parent", "root", "-m", "recover stale branch"], cwd=root)
    payload = parse_last_json_blob(created.stdout)
    assert payload["id"] == "exp_0000"
    assert (root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0000").exists()


def test_gate_flow(root: Path) -> None:
    """Test gate add/list/remove and gate blocking during run."""
    # Set up a multi-task benchmark that reports per-task scores
    write(
        root / "agent.py",
        'STATE = "baseline"\n',
    )
    write(
        root / "eval.py",
        """from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
score = 1.0 if "GOOD" in content else 0.5
traces_dir = os.environ.get("GEPA_RESEARCH_TRACES_DIR")
if traces_dir:
    Path(traces_dir).mkdir(parents=True, exist_ok=True)
print(json.dumps({"score": score, "tasks": {"0": score, "1": score}}))
""",
    )
    # Gate that checks a specific behavior is preserved
    write(
        root / "gate_refund.py",
        """from __future__ import annotations
import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
# Fails if agent contains BREAK_REFUND
sys.exit(1 if "BREAK_REFUND" in content else 0)
""",
    )
    write(
        root / "gate_cancel.py",
        """from __future__ import annotations
import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True)
args = parser.parse_args()
content = Path(args.agent).read_text(encoding="utf-8")
# Fails if agent contains BREAK_CANCEL
sys.exit(1 if "BREAK_CANCEL" in content else 0)
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: gates"], cwd=root)

    # Init workspace
    gepa_research(["init", "--target", "agent.py", "--benchmark", "python eval.py --agent {target}", "--metric", "max"], cwd=root)

    # Add a gate on root
    gepa_research(["gate", "add", "root", "--name", "refund_flow", "--command", "python gate_refund.py --agent {target}"], cwd=root)

    # List gates on root
    gate_list = json.loads(gepa_research(["gate", "list", "root"], cwd=root).stdout)
    assert len(gate_list) == 1
    assert gate_list[0]["name"] == "refund_flow"
    assert gate_list[0]["from"] == "root"

    # Baseline -- should pass (no BREAK_REFUND)
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    baseline = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000" in baseline.stdout

    # Add another gate on exp_0000 (child inherits root gate + this one)
    gepa_research(["gate", "add", "exp_0000", "--name", "cancel_flow", "--command", "python gate_cancel.py --agent {target}"], cwd=root)

    # List effective gates on exp_0000 -- should see both
    gate_list = json.loads(gepa_research(["gate", "list", "exp_0000"], cwd=root).stdout)
    assert len(gate_list) == 2
    names = {g["name"] for g in gate_list}
    assert names == {"refund_flow", "cancel_flow"}

    # `gepa-research get` returns effective gates (own + inherited) and exposes
    # own-only gates under `own_gates`. exp_0000 inherits refund_flow
    # from root and owns cancel_flow.
    got = json.loads(gepa_research(["get", "exp_0000"], cwd=root).stdout)
    assert {g["name"] for g in got["gates"]} == {"refund_flow", "cancel_flow"}
    assert {g["name"] for g in got["own_gates"]} == {"cancel_flow"}

    # For root, effective and own are identical.
    got_root = json.loads(gepa_research(["get", "root"], cwd=root).stdout)
    assert {g["name"] for g in got_root["gates"]} == {"refund_flow"}
    assert {g["name"] for g in got_root["own_gates"]} == {"refund_flow"}

    # Experiment that improves score but breaks the refund gate
    gepa_research(["new", "--parent", "exp_0000", "-m", "break refund"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0001" / "agent.py", 'STATE = "GOOD BREAK_REFUND"\n')
    result = gepa_research(["run", "exp_0001"], cwd=root)
    assert "GATE_FAILED" in result.stdout
    assert "EVALUATED exp_0001" in result.stdout

    # Experiment that improves score but breaks the cancel gate (inherited from exp_0000)
    gepa_research(["new", "--parent", "exp_0000", "-m", "break cancel"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0002" / "agent.py", 'STATE = "GOOD BREAK_CANCEL"\n')
    result = gepa_research(["run", "exp_0002"], cwd=root)
    assert "GATE_FAILED" in result.stdout
    assert "EVALUATED exp_0002" in result.stdout

    # Experiment that passes all gates
    gepa_research(["new", "--parent", "exp_0000", "-m", "clean improvement"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0003" / "agent.py", 'STATE = "GOOD"\n')
    result = gepa_research(["run", "exp_0003"], cwd=root)
    assert "COMMITTED exp_0003" in result.stdout
    assert "GATE_FAILED" not in result.stdout

    # Remove a gate and verify
    gepa_research(["gate", "remove", "exp_0000", "--name", "cancel_flow"], cwd=root)
    gate_list = json.loads(gepa_research(["gate", "list", "exp_0000"], cwd=root).stdout)
    assert len(gate_list) == 1
    assert gate_list[0]["name"] == "refund_flow"

    # Verify gate_failures stored on evaluated (not yet discarded) node.
    graph = load_graph(root)
    assert graph["nodes"]["exp_0001"]["status"] == "evaluated"
    assert graph["nodes"]["exp_0002"]["status"] == "evaluated"
    assert "refund_flow" in graph["nodes"]["exp_0001"].get("gate_failures", [])
    assert "cancel_flow" in graph["nodes"]["exp_0002"].get("gate_failures", [])

    # Verify outcome.json per attempt captures gate detail
    outcome_001 = load_outcome(root, "exp_0001", 1)
    assert outcome_001["outcome"] == "evaluated"
    gate_by_name = {g["name"]: g for g in outcome_001["gates"]}
    assert gate_by_name["refund_flow"]["passed"] is False
    assert gate_by_name["refund_flow"]["from"] == "root"


def test_retry_cap_and_fix(root: Path) -> None:
    """Covers the v0.2 lifecycle: evaluated preserves worktree, cap blocks
    retries, fix-then-retry flips to committed, discard is explicit."""
    gepa_research(
        [
            "init",
            "--target",
            "agent.py",
            "--benchmark",
            "python eval.py --agent {target}",
            "--metric",
            "max",
        ],
        cwd=root,
    )
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    gepa_research(["run", "exp_0000"], cwd=root)
    gepa_research(["new", "--parent", "exp_0000", "-m", "first-good"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0001" / "agent.py", 'STATE = "GOOD"\n')
    gepa_research(["run", "exp_0001"], cwd=root)

    # Three evaluated attempts in a row to exhaust the cap.
    gepa_research(["new", "--parent", "exp_0001", "-m", "regression loop"], cwd=root)
    wt = root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0002"
    for _ in range(3):
        write(wt / "agent.py", 'STATE = "baseline"\n')
        result = gepa_research(["run", "exp_0002"], cwd=root)
        assert "EVALUATED exp_0002" in result.stdout

    graph = load_graph(root)
    assert graph["nodes"]["exp_0002"]["status"] == "evaluated"
    assert graph["nodes"]["exp_0002"]["evaluated_attempts"] == 3
    assert wt.exists(), "worktree preserved across evaluated retries"

    # Fourth run refused by cap.
    blocked = gepa_research(["run", "exp_0002"], cwd=root, check=False)
    assert blocked.returncode == 1
    assert "exhausted 3/3 attempts" in blocked.stderr

    # Each evaluated attempt wrote its own outcome.json.
    for i in (1, 2, 3):
        o = load_outcome(root, "exp_0002", i)
        assert o["outcome"] == "evaluated"
        assert o["attempt"] == i

    # Explicit discard on cap-exhausted node deletes both worktree and branch.
    gepa_research(["discard", "exp_0002", "--reason", "exhausted"], cwd=root)
    assert not wt.exists()
    branches = run(["git", "branch", "--list", "gepa-research/run_0000/exp_0002"], cwd=root).stdout.strip()
    assert not branches
    graph = load_graph(root)
    assert graph["nodes"]["exp_0002"]["status"] == "discarded"

    # Fix-then-retry from scratch: branch a new exp, regress once, then fix.
    gepa_research(["new", "--parent", "exp_0001", "-m", "fix flow"], cwd=root)
    wt3 = root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0003"
    write(wt3 / "agent.py", 'STATE = "baseline"\n')
    first = gepa_research(["run", "exp_0003"], cwd=root)
    assert "EVALUATED exp_0003" in first.stdout
    # Now agent fixes the edit in the SAME worktree and re-runs.
    write(wt3 / "agent.py", 'STATE = "GOOD v2"\n')
    second = gepa_research(["run", "exp_0003"], cwd=root)
    assert "COMMITTED exp_0003" in second.stdout
    graph = load_graph(root)
    assert graph["nodes"]["exp_0003"]["status"] == "committed"
    # Both attempt outcome.json files persist side by side.
    assert load_outcome(root, "exp_0003", 1)["outcome"] == "evaluated"
    assert load_outcome(root, "exp_0003", 2)["outcome"] == "committed"


def test_file_result_channel_wins_over_stdout_noise(root: Path) -> None:
    """A benchmark that writes result.json + prints diagnostic prose to stdout
    must be scored from the file, not from stdout."""
    write(
        root / "agent.py",
        'STATE = "baseline"\n',
    )
    write(
        root / "eval.py",
        """from __future__ import annotations
import json
import os
from pathlib import Path

result_path = os.environ["GEPA_RESEARCH_RESULT_PATH"]
Path(result_path).parent.mkdir(parents=True, exist_ok=True)
Path(result_path).write_text(json.dumps({"score": 0.77, "tasks": {"0": 0.77}}))

# Diagnostic prose. Pre-port this would've spuriously matched the loose
# parse_score regex (`score: ...` line) and short-circuited to 0.99.
print("INFO: starting evaluation")
print("WARN: synthetic warning, score: 0.99 — should be ignored")
print("DONE")
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: file channel"], cwd=root)

    gepa_research(["init", "--target", "agent.py", "--benchmark", "python eval.py", "--metric", "max"], cwd=root)
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    out = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 0.77" in out.stdout, out.stdout

    graph = load_graph(root)
    assert graph["nodes"]["exp_0000"]["score"] == 0.77
    # Confirm the actual file was the source: outcome.benchmark.result must be
    # the parsed file content, including 'tasks'.
    outcome = load_outcome(root, "exp_0000", 1)
    parsed = outcome["benchmark"]["result"]
    assert parsed["score"] == 0.77
    assert parsed["tasks"] == {"0": 0.77}


def test_gate_env_stripped_so_benchmark_derived_gate_cant_clobber(root: Path) -> None:
    """A benchmark-derived gate inheriting GEPA_RESEARCH_* would either
    clobber the benchmark's result.json or fail-fast on its O_EXCL claim,
    polluting attempt status. The gate-env strip in cli.cmd_run prevents both
    by hiding GEPA_RESEARCH_RESULT_PATH (and the rest of the prefix) from
    gate subprocesses."""
    write(
        root / "agent.py",
        'STATE = "baseline"\n',
    )
    # Benchmark uses the file channel.
    write(
        root / "eval.py",
        """from __future__ import annotations
import json
import os
from pathlib import Path

result_path = os.environ["GEPA_RESEARCH_RESULT_PATH"]
Path(result_path).parent.mkdir(parents=True, exist_ok=True)
Path(result_path).write_text(json.dumps({"score": 0.42, "tasks": {"0": 0.42}}))
""",
    )
    # Gate that dumps its visible GEPA_RESEARCH_* env to a sidecar so the
    # test can assert the strip happened. Also asserts the benchmark's
    # result.json is unchanged before/after the gate runs.
    write(
        root / "gate_env_dump.py",
        """from __future__ import annotations
import json
import os
import sys
from pathlib import Path

env_dump = {k: v for k, v in os.environ.items() if k.startswith("GEPA_RESEARCH_")}
sidecar = Path(os.environ.get("HOME", "/tmp")) / "gepa_research_gate_env_dump.json"
sidecar.write_text(json.dumps(env_dump))
sys.exit(0)
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: gate env"], cwd=root)

    gepa_research(["init", "--target", "agent.py", "--benchmark", "python eval.py", "--metric", "max"], cwd=root)
    gepa_research(["gate", "add", "root", "--name", "env_dump", "--command", "python gate_env_dump.py"], cwd=root)

    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    out = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 0.42" in out.stdout, out.stdout

    sidecar = Path(os.environ.get("HOME", "/tmp")) / "gepa_research_gate_env_dump.json"
    try:
        env_dump = json.loads(sidecar.read_text(encoding="utf-8"))
    finally:
        sidecar.unlink(missing_ok=True)

    # The whole prefix must be stripped. Specifically RESULT_PATH and TRACES_DIR
    # are the dangerous ones; assert no GEPA_RESEARCH_* leaks at all.
    assert env_dump == {}, f"gate inherited GEPA_RESEARCH_* env: {env_dump}"


def test_optimize_uses_file_channel(root: Path) -> None:
    """gepa_adapter.evaluate() must read from result.json when the benchmark
    writes there, mirroring cli.cmd_run. Stdout-only benchmarks are exercised
    by test_optimize_smoke; this test specifically covers the file path
    through the adapter."""
    write(
        root / "agent.py",
        'STATE = "GOOD"\n',
    )
    write(
        root / "eval.py",
        """from __future__ import annotations
import json
import os
from pathlib import Path

result_path = os.environ["GEPA_RESEARCH_RESULT_PATH"]
Path(result_path).parent.mkdir(parents=True, exist_ok=True)
# Score is 1.0 regardless of agent (we only need the smoke).
Path(result_path).write_text(json.dumps({"score": 1.0, "tasks": {"0": 1.0}}))
print("INFO: noisy stdout that should be ignored")
""",
    )
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-m", "fixture: file-channel optimize"], cwd=root)

    gepa_research(["init", "--target", "agent.py", "--benchmark", "python eval.py", "--metric", "max"], cwd=root)
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    baseline = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 1.0" in baseline.stdout, baseline.stdout

    result = gepa_research(
        ["optimize", "--max-metric-calls", "1", "--stall", "0"],
        cwd=root,
    )
    summary = parse_last_json_blob(result.stdout)
    assert summary["total_metric_calls"] == 1, summary
    assert summary["num_candidates"] >= 1

    # The seed evaluation goes through gepa_adapter.evaluate() and must have
    # picked up the file-written score, not parsed it from stdout. Stdout
    # contains "INFO: noisy ..." which strict parse_score would reject.
    graph = load_graph(root)
    seed = graph["nodes"]["exp_0001"]
    assert seed["status"] in {"committed", "evaluated"}, seed
    assert seed["score"] == 1.0, seed
    assert seed["benchmark_result"]["tasks"] == {"0": 1.0}, seed["benchmark_result"]


def test_optimize_smoke(root: Path) -> None:
    """Hermetic smoke test for `gepa-research optimize`.

    Budget of 1 metric call means the stopper fires after seed evaluation,
    before any reflection LM call — so this runs without an API key.
    """
    gepa_research(
        [
            "init",
            "--target",
            "agent.py",
            "--benchmark",
            "python eval.py --agent {target}",
            "--metric",
            "max",
        ],
        cwd=root,
    )
    gepa_research(["new", "--parent", "root", "-m", "baseline"], cwd=root)
    write(root / ".gepa-research" / "run_0000" / "worktrees" / "exp_0000" / "agent.py", 'STATE = "GOOD"\n')
    baseline = gepa_research(["run", "exp_0000"], cwd=root)
    assert "COMMITTED exp_0000 1.0" in baseline.stdout

    result = gepa_research(
        ["optimize", "--max-metric-calls", "1", "--stall", "0"],
        cwd=root,
    )
    summary = parse_last_json_blob(result.stdout)
    assert summary["total_metric_calls"] == 1, f"reflection should not fire with budget=1: {summary!r}"
    assert summary["num_candidates"] >= 1

    graph = load_graph(root)
    assert graph["nodes"]["exp_0000"]["status"] == "committed"
    assert graph["nodes"]["exp_0000"]["score"] == 1.0
    seed_eval = graph["nodes"].get("exp_0001")
    assert seed_eval is not None, "optimize should allocate a node for the seed evaluation"
    assert seed_eval["status"] in {"committed", "evaluated"}
    assert seed_eval["score"] == 1.0

    progress = json.loads((root / ".gepa-research" / "run_0000" / "progress.json").read_text(encoding="utf-8"))
    assert progress["status"] == "done"
    assert progress["metric_calls_used"] == 1


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="gepa-research-e2e-"))
    try:
        max_repo = temp_root / "max-repo"
        max_repo.mkdir()
        init_repo(max_repo)
        setup_max_repo(max_repo)
        test_max_flow(max_repo)

        min_repo = temp_root / "min-repo"
        min_repo.mkdir()
        init_repo(min_repo)
        setup_min_repo(min_repo)
        test_min_flow(min_repo)

        stale_repo = temp_root / "stale-repo"
        stale_repo.mkdir()
        init_repo(stale_repo)
        setup_max_repo(stale_repo)
        test_stale_branch_recovery(stale_repo)

        gate_repo = temp_root / "gate-repo"
        gate_repo.mkdir()
        init_repo(gate_repo)
        test_gate_flow(gate_repo)

        retry_repo = temp_root / "retry-repo"
        retry_repo.mkdir()
        init_repo(retry_repo)
        setup_max_repo(retry_repo)
        test_retry_cap_and_fix(retry_repo)

        smoke_repo = temp_root / "optimize-smoke-repo"
        smoke_repo.mkdir()
        init_repo(smoke_repo)
        setup_max_repo(smoke_repo)
        test_optimize_smoke(smoke_repo)

        file_channel_repo = temp_root / "file-channel-repo"
        file_channel_repo.mkdir()
        init_repo(file_channel_repo)
        test_file_result_channel_wins_over_stdout_noise(file_channel_repo)

        gate_strip_repo = temp_root / "gate-strip-repo"
        gate_strip_repo.mkdir()
        init_repo(gate_strip_repo)
        test_gate_env_stripped_so_benchmark_derived_gate_cant_clobber(gate_strip_repo)

        adapter_file_repo = temp_root / "adapter-file-channel-repo"
        adapter_file_repo.mkdir()
        init_repo(adapter_file_repo)
        test_optimize_uses_file_channel(adapter_file_repo)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("E2E OK")


if __name__ == "__main__":
    main()
