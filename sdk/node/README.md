# gepa-research (Node SDK)

Lightweight reporting SDK for [GEPAResearch](https://github.com/CyrusNuevoDia/geparesearch) experiments. Zero dependencies, ESM-only, Node 18+.

Mirrors the `gepa-research-agent` Python SDK surface: `Run` for per-task logging + scoring, `Gate` for safety checks with exit codes.

## Install

```bash
npm install gepa-research
```

## Usage

### Benchmark (Run)

```js
import { Run } from 'gepa-research';

const run = new Run();
for (const task of tasks) {
  run.log(task.id, 'starting task');
  const result = await evaluate(task);
  run.log(task.id, { output: result.output });
  run.report(task.id, {
    score: result.score,
    summary: `reward=${result.score.toFixed(2)}`,
    failureReason: result.passed ? undefined : 'task_failed',
  });
}
await run.finish();
```

On `finish()`:
- Prints the score JSON to stdout (the contract gepa-research reads).
- Per-task trace files are written to `$GEPA_RESEARCH_TRACES_DIR` as each `report()` is called.

### Gate

```js
import { Gate } from 'gepa-research';

const gate = new Gate();
for (const task of criticalTasks) {
  const result = await evaluate(task);
  gate.check(task.id, { score: result.score, detail: `reward=${result.score.toFixed(2)}` });
}
gate.finish();  // exits 0 if all passed, 1 otherwise
```

## Environment

- `GEPA_RESEARCH_TRACES_DIR`   directory where `task_<id>.json` files are written (set by `gepa-research run`)
- `GEPA_RESEARCH_EXPERIMENT_ID`  experiment label embedded in each trace

Both are set automatically when the gepa-research CLI spawns your benchmark. Missing vars are tolerated -- traces are just skipped.
