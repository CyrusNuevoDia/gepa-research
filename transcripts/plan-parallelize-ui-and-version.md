<!-- Second /make application in the same session, after a context-overflow continuation.
     Edited only by the redaction pass in scripts/render_transcripts.py (now removed). -->

# Plan: parallelize GEPA iterations, refresh UI, pin version to 0.1.0

## Context

The Evo → GEPAResearch rebrand (previous plan) landed. Three follow-ups remain before a first tagged release:

1. **Parallelism regression.** Old Evo fanned out 5 subagents per round in parallel worktrees. The new adapter (`plugins/gepa-research/src/gepa_research/gepa_adapter.py`) sets `EngineConfig(parallel=False)` defensively — we paid that cost assuming GEPA was strictly serial. It isn't: GEPA supports **intra-iteration parallelism** via `num_parallel_proposals`, which spins up N independent reflective proposals in a `ThreadPoolExecutor` (each runs evaluate→propose→evaluate end-to-end, then acceptances process serially). Verified at `gepa/src/gepa/core/engine.py:381-452` — the batch pre-samples N parent contexts sequentially, executes N `reflective_proposer.execute_proposal` calls concurrently, then applies acceptances. That means our `adapter.evaluate` is called from N threads simultaneously on distinct candidates.
2. **Dashboard still frames output as a subagent tree.** Panel title says "Experiment Tree"; no GEPA-specific surfaces (budget burndown, stall counter, Pareto frontier, best_idx highlight). `graph.json` schema is already compatible — just copy + a couple new widgets.
3. **Version is at 0.2.2** (Evo's last). First release under the new name should be `0.1.0`.

## Intended outcome

- `gepa-research optimize --num-parallel-proposals 4` evaluates 4 candidates per iteration concurrently, each in its own worktree, without races on `graph.json`.
- Dashboard reads as a GEPA dashboard, not a tree-search dashboard: budget + stall visible, "Candidate Lineage" labeling, frontier/best highlighted.
- All 8 version strings read `0.1.0`; `scripts/check_versions.py` passes.

## Thread-safety verification (already satisfied)

`plugins/gepa-research/src/gepa_research/core.py` uses `advisory_lock(lock_file_for(graph_path(root)))` around every graph mutation:
- `allocate_experiment` (line 372) — each thread gets a unique `exp_NNNN` and its own worktree directory
- `update_node` (line 662) — all status mutations serialize on the lock

Each worktree is a separate directory, so concurrent `git`/benchmark subprocesses don't collide. Each evaluator call does `env = os.environ.copy()` before setting `GEPA_RESEARCH_*` keys (`gepa_adapter.py:131`), so env pollution across threads is impossible. No adapter-level code changes needed for correctness — only to turn the switch on.

## Changes

### A. Enable parallel proposals

**`plugins/gepa-research/src/gepa_research/gepa_adapter.py`** — in `run_gepa_optimize`:
- Add parameter `num_parallel_proposals: int = 1` (default preserves current serial behavior).
- Flip `engine_kwargs["parallel"] = True` (it's GEPA's default anyway — the current `False` was defensive).
- Set `engine_kwargs["num_parallel_proposals"] = num_parallel_proposals`.
- Drop the outdated comment that claims "we serialize because each candidate takes an exclusive worktree" — replace with a one-liner: each evaluator call allocates its own worktree; graph writes are lock-protected.

**`plugins/gepa-research/src/gepa_research/cli.py`** — `cmd_optimize`:
- Add `--num-parallel-proposals N` flag (int; default 1).
- Pass through to `run_gepa_optimize`.
- Also accept `num_parallel_proposals` field in `config.json` so `gepa-research init --num-parallel-proposals` can pre-set it (mirrors existing `--reflection-lm`, `--objective`, `--background` pattern). `cmd_init` already persists ad-hoc fields — just extend the field list.

**`plugins/gepa-research/skills/optimize/SKILL.md`** — swap the lines that forbid parallelism:
- Current: "Parallel candidate evaluation across worktrees is disabled for safety" → rewrite: "Use `--num-parallel-proposals N` (default 1) to evaluate N candidates per GEPA iteration concurrently; each gets its own worktree."
- Current: "Do not spawn parallel subagents — the GEPA engine drives candidate proposal and acceptance serially." → rewrite: "GEPA's reflective proposer pre-samples N parent contexts sequentially, then runs N evaluate→propose→evaluate pipelines concurrently in a thread pool. Acceptances are still processed serially, so each iteration commits at most N new candidates."
- Note the tradeoff: N parallel proposals burn N× the reflection-LM budget per iteration; set `--max-metric-calls` accordingly.

### B. Dashboard UI refresh

The work splits into text-only relabeling (quick) and new panels (slightly more involved). Keep schema-compatible — no graph.json migration.

**Text-only (do first):**

- `plugins/gepa-research/src/gepa_research/static/index.html:73` — `Experiment Tree` → `Candidate Lineage`
- `plugins/gepa-research/src/gepa_research/static/index.html:82` — `Experiments` → `Candidates` (optional; or keep "Experiments" since our own nomenclature is stable)
- `plugins/gepa-research/src/gepa_research/static/index.html:67` — `Score Progression` stays
- `plugins/gepa-research/src/gepa_research/static/app.js:328` — x-axis label `'experiment #'` → `'candidate #'`

Structural `tree*` class names (`treeTransform`, `.tree-link`, `.tree-container`, `d3.tree()`) are D3 API + CSS selectors; leave them. No user sees them.

**New panels (add next):**

1. **Budget + stall hero metrics** — two new cards in the hero strip (`index.html:40-61`):
   - `BUDGET` → `X / max_metric_calls` (e.g., `27 / 50`) with a thin progress bar underneath
   - `STALL` → `N / stall_limit` iterations without improvement
   Requires persisting these to `graph.json` (or a sibling `progress.json`) from `run_gepa_optimize` after each iteration. Simplest: add an `on_iteration_end`-style callback to GEPA's `callbacks` list that writes `{total_metric_calls, iterations_without_improvement, stall_limit, max_metric_calls}` to `.gepa-research/<run>/progress.json` under the same `advisory_lock`. Expose via new `GET /api/progress` endpoint in `dashboard.py`. Poll alongside `/api/stats`.

2. **Best-candidate highlight** — in the table (`app.js:523-587`), add a gold/star badge next to the ID of the row matching `GEPAResult.best_candidate_idx`. Persist `best_idx` to `progress.json` from the callback.

3. **Pareto frontier panel** (deferred to nice-to-have; skip unless time permits). Would render `per_val_instance_best_candidates` as a heatmap. Only meaningful once we support multi-task `dataset`, which single-task benchmarks don't exercise.

**Files touched for UI:**
- `plugins/gepa-research/src/gepa_research/static/index.html` — relabel + new hero cards
- `plugins/gepa-research/src/gepa_research/static/app.js` — render new cards, add `/api/progress` fetch, star best row
- `plugins/gepa-research/src/gepa_research/static/style.css` — style the new cards + progress bar + star badge
- `plugins/gepa-research/src/gepa_research/dashboard.py` — add `/api/progress` route (reads `progress.json`)
- `plugins/gepa-research/src/gepa_research/gepa_adapter.py` — add `GEPAProgressCallback` class that writes `progress.json` on `on_iteration_end`; register it in `run_gepa_optimize`

### C. Version → 0.1.0

Eight files to edit (one edit each, mechanical):

1. `plugins/gepa-research/pyproject.toml:3` → `version = "0.1.0"`
2. `plugins/gepa-research/src/gepa_research/__init__.py:6` → `__version__ = "0.1.0"`
3. `plugins/gepa-research/.claude-plugin/plugin.json:3` → `"version": "0.1.0"`
4. `plugins/gepa-research/.codex-plugin/plugin.json:3` → `"version": "0.1.0"`
5. `sdk/python/pyproject.toml:3` → `version = "0.1.0"`
6. `sdk/python/src/gepa_research_agent/__init__.py:8` → `__version__ = "0.1.0"`
7. `sdk/node/package.json:3` → `"version": "0.1.0"`
8. `README.md:27` → update install-output example line (cosmetic — shows `0.2.2` in a `uv pip install` snippet)

`scripts/check_versions.py` already asserts all 7 sources match — it will fail closed if we miss one.

Regenerate lockfiles: `uv lock` inside `plugins/gepa-research` and `sdk/python`; `npm install` inside `sdk/node` to update `package-lock.json`.

## Verification

1. `python3 scripts/check_versions.py` → "OK: all 7 sources report version 0.1.0"
2. `uv run --project plugins/gepa-research gepa-research --version` → `gepa-research-cli 0.1.0`
3. End-to-end parallelism smoke test:
   - `cd tests/fixtures/tau3_demo && gepa-research init --target fixture.py --benchmark "bash benchmark.sh" --metric max`
   - Commit a baseline node manually (`gepa-research run` with a trivial diff) so there's a parent other than `root`.
   - `gepa-research optimize --max-metric-calls 8 --num-parallel-proposals 4` — watch `.gepa-research/run_0000/worktrees/` for 4 concurrent `exp_*` dirs during iteration 1.
   - Confirm `graph.json` gains 4 new nodes from that iteration and no `update_node` race trace in stderr.
4. Dashboard smoke: `gepa-research-dashboard` during the optimize run. Confirm:
   - Hero strip shows BUDGET (e.g., `5/8`) and STALL counters
   - Panel reads "Candidate Lineage" (not "Experiment Tree")
   - Best candidate row has a star/gold badge
5. Unit tests: `uv run --with pytest pytest tests/unit/` (7/7) still passes.
6. SDK tests: `cd sdk/python && uv run --with pytest pytest test/` (6/6) still passes.

## Critical files

**Modified:**
- `plugins/gepa-research/src/gepa_research/gepa_adapter.py` — enable parallel, add progress callback
- `plugins/gepa-research/src/gepa_research/cli.py` — add `--num-parallel-proposals`, persist in `cmd_init`
- `plugins/gepa-research/src/gepa_research/dashboard.py` — add `/api/progress`
- `plugins/gepa-research/src/gepa_research/static/{index.html,app.js,style.css}` — relabel + new cards
- `plugins/gepa-research/skills/optimize/SKILL.md` — rewrite parallelism section
- 8 version-string files (listed above)

**Added:**
- `.gepa-research/<run>/progress.json` (runtime artifact, gitignored via existing `.gepa-research/` entry)

**Not touched:**
- `graph.json` schema (compatible as-is)
- Dashboard structural code (tree layout, drawer, scatter chart)
- SDK (only version string changes)

## Risks

1. **Reflection LM cost blow-up.** `num_parallel_proposals=N` issues N reflection calls per iteration. Document in skill doc; default stays at 1.
2. **Worktree allocation contention.** All N threads briefly serialize on `graph.json.lock`. `allocate_experiment` is fast (no network), so the lock window is milliseconds per thread — acceptable.
3. **Subprocess fan-out.** N concurrent benchmark subprocesses may overwhelm a laptop. Document that `num_parallel_proposals` should stay ≤ available CPU cores / benchmark concurrency.
4. **GEPA's own `parallel=True` also spawns `ThreadPoolExecutor(max_workers=os.cpu_count())` for intra-candidate eval** (`optimize_anything_adapter.py`). In single-task mode the dataset has 1 example, so this is a no-op. In multi-task mode, total threads = `num_parallel_proposals × num_examples`. If we ever support multi-task, revisit worker caps.
5. **`progress.json` race.** The new callback writes from whichever thread reaches `on_iteration_end`. Use the same `advisory_lock` pattern as `update_node`. The callback must be registered via GEPA's `callbacks` config — confirm the API allows custom callbacks by reading `gepa/src/gepa/core/engine.py:notify_callbacks` before implementing.
