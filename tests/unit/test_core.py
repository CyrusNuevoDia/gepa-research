"""Unit tests for pure functions in gepa_research.core.

Fast (millisecond) tests for logic that does not touch git, subprocess, or
the filesystem. Complements the slower tests/e2e.py flow tests.

Run: `python3 tests/unit/test_core.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "gepa-research" / "src"))

import json
import tempfile

from gepa_research.core import (  # noqa: E402
    collect_gates_from_path,
    load_result,
    parse_score,
    path_to_node,
)


def _graph(*nodes: dict) -> dict:
    return {"nodes": {n["id"]: n for n in nodes}}


def _node(id_: str, parent: str | None, gates: list[dict] | None = None, **extra) -> dict:
    return {"id": id_, "parent": parent, "gates": gates or [], **extra}


def _gate(name: str, command: str = "cmd") -> dict:
    return {"name": name, "command": command, "added_at": "2026-04-15T00:00:00Z"}


def test_path_to_node_returns_root_to_leaf_chain() -> None:
    graph = _graph(
        _node("root", None),
        _node("exp_0000", "root"),
        _node("exp_0001", "exp_0000"),
    )
    chain = [n["id"] for n in path_to_node(graph, "exp_0001")]
    assert chain == ["root", "exp_0000", "exp_0001"], chain


def test_collect_gates_empty_when_no_gates_anywhere() -> None:
    graph = _graph(_node("root", None), _node("exp_0000", "root"))
    assert collect_gates_from_path(graph, "exp_0000") == []


def test_collect_gates_inherits_root_gate() -> None:
    graph = _graph(
        _node("root", None, gates=[_gate("core_tests", "pytest -x")]),
        _node("exp_0000", "root"),
    )
    gates = collect_gates_from_path(graph, "exp_0000")
    assert [g["name"] for g in gates] == ["core_tests"]
    assert gates[0]["command"] == "pytest -x"


def test_collect_gates_unions_root_and_own_gates_in_root_to_leaf_order() -> None:
    graph = _graph(
        _node("root", None, gates=[_gate("root_gate")]),
        _node("exp_0000", "root", gates=[_gate("own_gate")]),
    )
    gates = collect_gates_from_path(graph, "exp_0000")
    assert [g["name"] for g in gates] == ["root_gate", "own_gate"]


def test_collect_gates_dedupes_by_name_keeping_ancestor_wins() -> None:
    # Same gate name declared on an ancestor and a descendant: the ancestor
    # one is kept (ancestors are walked first), the descendant redeclaration
    # is ignored. Verifies we do not surface the gate twice.
    graph = _graph(
        _node("root", None, gates=[_gate("flaky", "pytest ancestor")]),
        _node("exp_0000", "root", gates=[_gate("flaky", "pytest descendant")]),
    )
    gates = collect_gates_from_path(graph, "exp_0000")
    assert len(gates) == 1
    assert gates[0]["command"] == "pytest ancestor"


def test_collect_gates_scoped_to_ancestry_not_siblings() -> None:
    graph = _graph(
        _node("root", None, gates=[_gate("root_gate")]),
        _node("exp_0000", "root", gates=[_gate("sibling_gate")]),
        _node("exp_0001", "root"),
    )
    gates = collect_gates_from_path(graph, "exp_0001")
    assert [g["name"] for g in gates] == ["root_gate"]


def test_collect_gates_on_root_returns_own_only() -> None:
    graph = _graph(_node("root", None, gates=[_gate("core_tests")]))
    gates = collect_gates_from_path(graph, "root")
    assert [g["name"] for g in gates] == ["core_tests"]


# ---- parse_score (strict): one JSON object with 'score' or raise -------- #

def test_parse_score_accepts_clean_json_object() -> None:
    score, parsed = parse_score('{"score": 0.75, "tasks": {"0": 1.0}}')
    assert score == 0.75
    assert parsed == {"score": 0.75, "tasks": {"0": 1.0}}


def test_parse_score_accepts_indented_multiline_json() -> None:
    score, parsed = parse_score('{\n  "score": 0.5,\n  "tasks": {}\n}')
    assert score == 0.5
    assert parsed["tasks"] == {}


def test_parse_score_rejects_empty() -> None:
    try:
        parse_score("")
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError on empty stdout")


def test_parse_score_rejects_bare_number() -> None:
    # Used to be accepted by the loose fallbacks; strict parser must reject.
    try:
        parse_score("0.42")
    except ValueError as exc:
        assert "missing 'score'" in str(exc) or "not a single JSON" in str(exc).lower() or "JSON missing" in str(exc)
    else:
        raise AssertionError("expected ValueError on bare number")


def test_parse_score_rejects_score_colon_regex() -> None:
    # Used to match `score: 0.5` via regex; strict parser must reject.
    try:
        parse_score("INFO: completed\nscore: 0.5\n")
    except ValueError as exc:
        msg = str(exc)
        assert "JSON" in msg or "single JSON object" in msg
    else:
        raise AssertionError("expected ValueError on 'score: 0.5' line")


def test_parse_score_rejects_last_line_json_with_noise_above() -> None:
    # Used to scan lines bottom-up and accept the last parseable JSON line.
    noisy = 'WARN: slow\n{"unrelated": true}\n{"score": 0.9}\n'
    try:
        parse_score(noisy)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on multi-line stdout with noise")


def test_parse_score_rejects_json_object_without_score() -> None:
    try:
        parse_score('{"tasks": {"0": 1.0}}')
    except ValueError as exc:
        assert "score" in str(exc)
    else:
        raise AssertionError("expected ValueError on object missing 'score'")


# ---- load_result: file wins (strict) when present, else parse_score ------ #

def test_load_result_reads_file_when_present() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        path.write_text('{"score": 0.81, "tasks": {"0": 1.0, "1": 0.62}}')
        score, parsed = load_result(path, "noisy stdout that should be ignored")
        assert score == 0.81
        assert parsed["tasks"]["1"] == 0.62


def test_load_result_falls_back_to_stdout_when_file_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        score, parsed = load_result(path, '{"score": 0.33}')
        assert score == 0.33
        assert parsed == {"score": 0.33}


def test_load_result_raises_on_empty_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        path.write_text("")
        try:
            load_result(path, '{"score": 0.5}')
        except ValueError as exc:
            assert "empty" in str(exc) and "crashed" in str(exc)
        else:
            raise AssertionError("expected ValueError on empty file")


def test_load_result_raises_on_malformed_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        path.write_text("not json")
        try:
            load_result(path, '{"score": 0.5}')
        except ValueError as exc:
            assert "not valid JSON" in str(exc)
        else:
            raise AssertionError("expected ValueError on malformed file")


def test_load_result_raises_on_missing_score_field_in_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        path.write_text(json.dumps({"tasks": {"0": 1.0}}))
        try:
            load_result(path, '{"score": 0.5}')
        except ValueError as exc:
            assert "missing 'score'" in str(exc)
        else:
            raise AssertionError("expected ValueError on file missing 'score'")


def test_load_result_does_not_fall_back_when_file_present_but_invalid() -> None:
    # Critical: an invalid file must NOT silently fall through to stdout —
    # that would mask a real benchmark bug.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "result.json"
        path.write_text('{"unrelated": 1}')
        try:
            load_result(path, '{"score": 0.99}')
        except ValueError:
            pass
        else:
            raise AssertionError("must not fall back to stdout when file present and bad")


TESTS = [fn for name, fn in globals().items() if name.startswith("test_") and callable(fn)]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
