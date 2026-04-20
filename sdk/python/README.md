# gepa-research-agent (Python SDK)

Lightweight reporting SDK for [GEPAResearch](https://github.com/CyrusNuevoDia/geparesearch) experiments. Zero dependencies, Python 3.10+.

Mirrors the [`gepa-research`](https://www.npmjs.com/package/gepa-research) Node SDK surface: `Run` for per-task logging + scoring, `Gate` for safety checks with exit codes.

## Install

```bash
pip install gepa-research-agent
```

Install name and import name differ (same pattern as `python-dateutil` / `dateutil`):

```python
from gepa_research_agent import Run, Gate
```

## Usage

### Benchmark (Run)

```python
from gepa_research_agent import Run

with Run() as run:
    for task in tasks:
        run.log(task["id"], "starting task")
        result = evaluate(task)
        run.log(task["id"], {"output": result.output})
        run.report(
            task["id"],
            score=result.score,
            summary=f"reward={result.score:.2f}",
            failure_reason=None if result.passed else "task_failed",
        )
# finish() called automatically on __exit__:
#  - prints score JSON to stdout (the contract gepa-research reads)
#  - per-task trace files were written to $GEPA_RESEARCH_TRACES_DIR as each report() ran
```

### Gate

```python
from gepa_research_agent import Gate

with Gate() as gate:
    for task in critical_tasks:
        result = evaluate(task)
        gate.check(task["id"], score=result.score, detail=f"reward={result.score:.2f}")
# exits 0 if all passed, 1 otherwise
```

## Environment

- `GEPA_RESEARCH_TRACES_DIR`   directory where `task_<id>.json` files are written (set by `gepa-research run`)
- `GEPA_RESEARCH_EXPERIMENT_ID`  experiment label embedded in each trace

Both are set automatically when the gepa-research CLI spawns your benchmark. Missing vars are tolerated -- traces are just skipped.
