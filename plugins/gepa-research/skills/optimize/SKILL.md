---
name: optimize
description: Optimize the project's target file using the GEPA algorithm. Hands the seed candidate and evaluator to gepa.optimize_anything; each candidate GEPA proposes is evaluated inside an isolated git worktree with gates enforced. Runs until budget or stall is reached.
argument-hint: "[max-metric-calls=N] [stall=N] [reflection-lm=MODEL]"
---

Run the GEPA-backed optimization loop. The plugin calls
`gepa.optimize_anything` under the hood; each candidate it proposes is
applied in a fresh git worktree, the benchmark is run, gates are checked,
and the result is backported into `.gepa-research/<run>/graph.json` so the
dashboard continues to render the lineage DAG.

## Host conventions

- **Slash commands shown in user-facing copy** (e.g. `/gepa-research:optimize`) — translate to your host's mention syntax when speaking to the user (e.g. `$gepa-research optimize` on Codex, `/skill:gepa-research-optimize` on Pi).

## Configuration

All arguments are optional. Invoked as `/optimize [max-metric-calls=N] [stall=N] [reflection-lm=MODEL]`.

- **max-metric-calls** — GEPA evaluator-call budget for this run (default: `50`).
- **stall** — consecutive iterations without improvement before auto-stopping (default: `5`).
- **reflection-lm** — model string passed to `ReflectionConfig.reflection_lm` (default: gepa's default, currently `openai/gpt-5.1`). Use e.g. `anthropic/claude-opus-4-7` for Claude.

The legacy `subagents`, `budget`, and per-subagent knobs are no longer accepted — GEPA owns the search strategy.

## Prerequisites

- Workspace must be initialized (`gepa-research status` should succeed).
- A baseline experiment must be committed (run `/discover` first). GEPA's
  seed candidate is read from the current best committed node's target file.
- The `gepa` library on the Python path (auto-installed as a transitive dependency when the CLI is installed from GitHub: `uv tool install "git+https://github.com/CyrusNuevoDia/gepa-research#subdirectory=plugins/gepa-research"`).
- A reflection LM API key in the environment (OpenAI/Anthropic/etc., depending
  on the `reflection-lm` value). Without this the first GEPA iteration will fail.

## Architecture

```
Orchestrator (this skill):
  1. Reads current best committed node from .gepa-research/<run>/graph.json
  2. Extracts seed_candidate: {target_relpath: file_contents}
  3. Calls gepa.optimize_anything(seed, evaluator=adapter.evaluate,
                                  objective=config["optimization_objective"],
                                  config=GEPAConfig(stop_callbacks=...))
  4. Reports the final best candidate and updates the graph

GepaResearchAdapter.evaluate (called by gepa per candidate):
  a. allocate_experiment(parent_id=best_committed)
     -> creates .gepa-research/<run>/worktrees/exp_NNNN and a fresh branch
  b. write candidate dict contents into the worktree
  c. run config["benchmark"] as subprocess; parse_score from stdout
  d. run inherited gates (collect_gates_from_path)
     -> on failure, return (0.0, {"gate_failures": [...], "traces": ...})
  e. on score improvement + all gates pass: maybe_commit_worktree + mark "committed"
  f. return (score, side_info) so gepa can reflect on stdout/stderr/traces
```

`side_info` returned to gepa includes:
- `experiment_id` — so diagnostics reference `.gepa-research/<run>/experiments/<id>/`
- `stdout` / `stderr` — trailing 4 KB of each
- `benchmark_result` — parsed JSON (score + per-task breakdown, when available)
- `task_traces` — contents of `task_*.json` from the SDK, when instrumented
- `gate_failures` — list of gate names that rejected the candidate

GEPA uses this side_info in its reflection prompt to propose the next
candidate. For that to work well, your benchmark must write *diagnostic*
output (stack traces, task-level failure reasons, etc.) rather than just
a terminal score.

## The loop

Run once per `/optimize` invocation:

### 1. Verify prerequisites

```bash
gepa-research status                         # confirms workspace exists + shows current best
gepa-research-version-check                  # confirms CLI matches plugin manifest when wrapper is available
```

If `gepa-research-version-check` is not on PATH, run `gepa-research --version` instead and continue only if it prints `gepa-research-cli <version>`. This fallback is expected on hosts that load only skills and not plugin `bin/` wrappers. If `gepa-research` itself is missing, stop and tell the user to install the CLI with `uv tool install "git+https://github.com/CyrusNuevoDia/gepa-research#subdirectory=plugins/gepa-research"`.

If status shows no committed node, stop and tell the user to run the discover skill first.

### 2. Resolve the reflection LM

If the user passed `reflection-lm=…`, use that value verbatim. Otherwise,
read `config.json` for a `reflection_lm` field. If neither is set, leave it
unset — GEPA will use its own default (currently `openai/gpt-5.1`).

Before handing off to GEPA, verify the corresponding API key is in the
environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.). If missing, stop
and tell the user which env var to export; do **not** try to proceed — GEPA
will burn the metric budget failing to call the LM.

### 3. Invoke GEPA via the plugin command

The optimize entry point wraps the full call:

```bash
gepa-research optimize \
  --max-metric-calls 50 \
  --stall 5 \
  [--reflection-lm anthropic/claude-opus-4-7]
```

This resolves `parent_id = best_committed_node(graph, metric)` internally,
builds the seed candidate from that node's target file, and calls
`run_gepa_optimize` from `gepa_research.gepa_adapter`. Each candidate GEPA
proposes allocates a new worktree under `.gepa-research/<run>/worktrees/`.

### 4. Stream progress

While the loop is running, the dashboard (if started) auto-refreshes as new
experiment nodes appear in `graph.json`, and the BUDGET / STALL hero cards
update from `.gepa-research/<run>/progress.json`. Surface the URL to the user
if they don't already have it.

Do not run multiple `gepa-research optimize` invocations concurrently against
the same workspace — they would race on graph/meta file locks and corrupt the
lineage.

### 5. Final summary

When `gepa-research optimize` exits, print:
- Best score and the experiment id that produced it
- Total candidates evaluated (from GEPA's `total_metric_calls`)
- The winning diff: `gepa-research diff <best_exp_id>`
- Whether the stop was due to budget, stall, or user interrupt

Suggest follow-up actions: raise the budget, switch reflection LM, or
introduce additional gates if the winning candidate regressed something
the objective didn't capture.
