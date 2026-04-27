// Node SDK usage example. Install: `git clone https://github.com/CyrusNuevoDia/gepa-research /tmp/gepa-research && npm install /tmp/gepa-research/sdk/node` (npm does not natively support subdirectory git installs).
//
// The SDK auto-reads $GEPA_RESEARCH_TRACES_DIR and $GEPA_RESEARCH_EXPERIMENT_ID. Traces flush
// on each report() so the dashboard can stream progress live.

import { Run, Gate } from 'gepa-research';

// ---- Benchmark run ----

const run = new Run();
for (const task of tasks) {
  const result = await evaluate(task);
  run.log(task.id, { output: result.output });
  run.report(task.id, { score: result.score });
}
await run.finish();
// finish(): prints score JSON to stdout, writes task_<id>.json per task.

// ---- Gate (exits 0 all-pass / 1 any-fail) ----

const gate = new Gate();
for (const task of criticalTasks) {
  const result = await evaluate(task);
  gate.check(task.id, { score: result.score });
}
await gate.finish();
