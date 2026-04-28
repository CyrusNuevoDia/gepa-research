<!-- The plan Claude wrote during /make's Phase 3 (Plan), captured before execution.
     Edited only by the redaction pass in scripts/render_transcripts.py (now removed). -->

# Plan: Rename Evo → Gepa Research, replace inner loop with `gepa`

## Context

This repo (currently called **Evo**) is a plugin for agentic frameworks (Claude Code, Codex, OpenClaw, Hermes) that optimizes code through autonomous experiments. Today it implements its own search: a tree of experiments in git worktrees, with parallel semi-autonomous subagents fanning out each round. It does **not** use any external optimization library.

The user wants to:
1. **Rebrand** the project as **Gepa Research** (new identity, new package names, new repo at `github.com/CyrusNuevoDia/geparesearch`).
2. **Replace the inner loop** with calls to the [`gepa`](https://github.com/gepa-ai/gepa) library's `gepa.optimize_anything`, adopting its LLM-driven genetic-Pareto search in place of Evo's bespoke tree search.

This collapses the round-based subagent orchestration (serial Gepa iterations replace parallel fan-out), but gains the Pareto frontier, reflection-based candidate proposals, and a maintained external search engine.

**Naming (user-specified):**
- Human/display name: **Gepa Research**
- Python module: `gepa_research` (inside `plugins/gepa-research/src/`)
- Python SDK module: `gepa_research_agent` (inside `sdk/python/src/`)
- PyPI distributions: `gepa-research-cli`, `gepa-research-agent`
- npm package: `gepa-research` (unscoped; replaces `@evo-hq/evo-agent`)
- CLI binary: `gepa-research`
- Workspace directory: `.gepa-research/` (replaces `.evo/`)
- Git branch prefix for experiments: `refs/heads/gepa-research/`
- Repo URL: `https://github.com/CyrusNuevoDia/geparesearch`
- Plugin manifest `name`: `gepa-research`; marketplace IDs retargeted to `CyrusNuevoDia`

## Real Gepa API (verified against source, not blog)

From `~/<repo>/src/gepa/__init__.py`:

```python
from gepa.optimize_anything import optimize_anything
from gepa import GEPAAdapter, GEPAResult, EvaluationBatch, Image
from gepa import optimize  # lower-level API
```

`optimize_anything` signature (`src/gepa/optimize_anything.py:1119`):

```python
def optimize_anything(
    seed_candidate: str | Candidate | None = None,
    *,
    evaluator: Callable[..., Any],         # (candidate, example?) -> float | (float, side_info)
    dataset: list[DataInst] | None = None,
    valset: list[DataInst] | None = None,
    objective: str | None = None,
    background: str | None = None,
    config: GEPAConfig | None = None,
) -> GEPAResult
```

Gepa is library-only (no CLI), serial (no built-in parallelism), returns a `GEPAResult` with `.best_candidate`, `.candidates`, `.parents` (lineage DAG), `.val_aggregate_scores`, `.per_val_instance_best_candidates` (Pareto frontier).

## High-level plan

Execute in this order (earlier steps are low-risk renames; later steps change behavior):

### Phase A — Mechanical rename (behavior unchanged)

A1. **Directory renames**
- `plugins/evo/` → `plugins/gepa-research/`
- `plugins/gepa-research/src/evo/` → `plugins/gepa-research/src/gepa_research/`
- `sdk/python/src/evo_agent/` → `sdk/python/src/gepa_research_agent/`
- `plugins/gepa-research/bin/evo` → `plugins/gepa-research/bin/gepa-research`
- `plugins/gepa-research/bin/evo-version-check` → `plugins/gepa-research/bin/gepa-research-version-check`

A2. **Manifest/config updates**
- `plugins/gepa-research/pyproject.toml`: name → `gepa-research-cli`, scripts → `gepa-research = "gepa_research.cli:main"` and `gepa-research-dashboard = "gepa_research.dashboard:main"`, package-data key → `gepa_research = ["static/*"]`, URLs → `CyrusNuevoDia/geparesearch`. Add `gepa` to `dependencies`.
- `sdk/python/pyproject.toml`: name → `gepa-research-agent`, URLs updated.
- `sdk/node/package.json`: name → `gepa-research` (drop `@evo-hq/` scope), main/exports/keywords/repo.url/homepage/bugs all retargeted.
- `.claude-plugin/marketplace.json`: `name` → `CyrusNuevoDia-gepa-research`, `owner.name` → `CyrusNuevoDia`, plugin ids → `gepa-research`.
- `.agents/plugins/marketplace.json`: same treatment.
- `plugins/gepa-research/.claude-plugin/plugin.json`: `name` → `gepa-research`.
- `plugins/gepa-research/.codex-plugin/plugin.json`: `name` → `gepa-research`, author + repo URL updated.

A3. **Source-level renames (search/replace across code + docs)**
- Python imports: `from evo.` → `from gepa_research.`; `import evo` → `import gepa_research`; same for SDK (`evo_agent` → `gepa_research_agent`).
- Constants in `plugins/gepa-research/src/gepa_research/core.py`: `WORKSPACE_NAME = ".evo"` → `".gepa-research"`; helper name `evo_dir` → `gepa_research_dir`.
- Branch prefix `refs/heads/evo/` → `refs/heads/gepa-research/` (grep all occurrences).
- Env vars in SDK (`EVO_TRACES_DIR`, `EVO_EXPERIMENT_ID` in `sdk/python/src/.../_run.py`, `_gate.py`, and Node equivalents) → `GEPA_RESEARCH_TRACES_DIR`, `GEPA_RESEARCH_EXPERIMENT_ID`. Update every reader as well.
- State filenames stay the same (`graph.json`, `config.json`, `meta.json`, …) — only the container dir name changes.
- `DISTRIBUTION_NAME = "evo-hq-cli"` in `plugins/.../__init__.py` → `"gepa-research-cli"`.

A4. **CI / scripts**
- `.github/workflows/ci.yml` and `publish.yml`: update wheel build paths (`plugins/evo` → `plugins/gepa-research`), PyPI package names, npm package name, tag prefixes (`py-v*`, `node-v*`, `cli-v*` stay — they're generic).
- `scripts/check_versions.py`: update expected manifest names/paths.
- `scripts/evo`, `scripts/dashboard.py`, `scripts/graph.py`, `scripts/scratchpad.py`: rename/update `uv run --project plugins/evo` invocations.

A5. **Skills (text-only at this phase)**
- `plugins/gepa-research/skills/discover/SKILL.md`, `optimize/SKILL.md`, `subagent/SKILL.md`: text replace `evo` → `gepa-research` / `Gepa Research` where it's branding, and update install snippets to the new marketplace/CLI names. Algorithmic content (loop, subagent orchestration) is left untouched in phase A — it's rewritten in phase B.

A6. **Top-level docs**
- `README.md`: new title/banner caption, new install snippets, retargeted marketplace URLs, updated TODO, updated dev-install section.
- `NOTICE`: copyright line retargeted (`evo-hq` → `CyrusNuevoDia`).
- `assets/banner.png`: alt text updated in README; image file itself kept as-is (separate asset task if desired later).

A7. **Tests and fixtures**
- `tests/e2e.py`, `tests/unit/test_core.py`, `tests/skills/README.md`: update imports, subprocess invocations (`evo` → `gepa-research`), env var names, workspace dir references.
- `tests/fixtures/tau3_demo/`, `tests/fixtures/auto_harness_demo/`: update SDK imports (`evo_agent` → `gepa_research_agent`) and any direct file references (e.g., `.evo/` → `.gepa-research/`).

### Phase B — Replace the inner loop with `gepa`

B1. **Add adapter module** `plugins/gepa-research/src/gepa_research/gepa_adapter.py`:

```python
from gepa import GEPAAdapter, EvaluationBatch
from gepa.optimize_anything import optimize_anything

class GepaResearchAdapter:
    """Bridges gepa's candidate/evaluator protocol with gepa-research's
    git-worktree + benchmark-subprocess infrastructure."""
    def __init__(self, root: Path, config: dict, graph: dict): ...
    def evaluate(self, candidate, example=None) -> tuple[float, dict]:
        # 1. allocate worktree (reuse core.allocate_experiment / worktrees_path)
        # 2. apply candidate dict[str, str] to target files
        # 3. run benchmark subprocess; parse score via core.parse_score
        # 4. read traces from .gepa-research/run_*/traces/ dir
        # 5. run gates; if any fail, return (0.0, {"gate_failed": name, "traces": ...})
        # 6. commit worktree (reuse core.maybe_commit_worktree) or discard
        # 7. return (score, {"traces": ..., "stdout": ..., "stderr": ...})
```

The adapter reuses existing helpers in `core.py` rather than duplicating git/worktree logic: `allocate_experiment`, `worktrees_path`, `parse_score`, `compare_scores`, `maybe_commit_worktree`, `add_gate`, `update_node`.

B2. **Rewrite `optimize` skill driver**

Replace the orchestrator logic in `plugins/gepa-research/skills/optimize/SKILL.md` and its Python entry point with:

- Load current best committed node from `.gepa-research/<run>/graph.json`.
- Extract seed candidate as a `dict[str, str]` mapping target file paths → current contents (based on `config.json`'s declared optimization targets).
- Build dataset: if `config.json` declares a multi-task benchmark, pass `dataset=[...]`; else single-task mode (`dataset=None`).
- Call `optimize_anything(seed_candidate=seed, evaluator=adapter.evaluate, dataset=dataset, objective=config['optimization_objective'], config=GEPAConfig(...))`.
- Backport `GEPAResult.candidates` + `GEPAResult.parents` into `graph.json` so the dashboard keeps working (each Gepa candidate becomes a node with `parent` from `result.parents`).
- Stall/budget: express as Gepa `StopperProtocol` instances (`MaxMetricCallsStopper`, `NoImprovementStopper` from `gepa.utils.stop_condition`). The old `subagents`/`budget`/`stall` CLI args map to `max_metric_calls` and `NoImprovementStopper(patience=stall)`; `subagents` is accepted but ignored (or deprecated with a warning) since Gepa is serial.

B3. **Prune what's no longer needed**

- Delete `plugins/gepa-research/skills/subagent/` — Gepa owns search; there are no more subagent briefs.
- In `core.py`, remove functions tied exclusively to subagent orchestration (brief serialization, round bookkeeping, orchestrator-specific scratchpad helpers) once confirmed unreferenced. Keep: `parse_score`, `compare_scores`, worktree/git helpers, graph load/save, `allocate_experiment`, `update_node`, `add_gate`, `maybe_commit_worktree`.
- Dashboard (`dashboard.py` + `static/app.js`): graph JSON schema is compatible (nodes still have `id`, `parent`, `score`, `status`); re-label "Tree" → "Candidate lineage" in UI copy. Pareto-frontier visualization is nice-to-have and deferred.

B4. **`discover` skill stays mostly as-is** — it's about benchmark discovery and instrumentation, not search. Update its output to write `.gepa-research/<run>/config.json` with fields the new adapter expects (notably: declared optimization target files for seed extraction, and the `optimization_objective` string passed to `optimize_anything`).

### Phase C — Verification

- `cd plugins/gepa-research && uv run gepa-research --version` prints `gepa-research-cli <version>`.
- `uv run --project plugins/gepa-research python -c "from gepa_research.gepa_adapter import GepaResearchAdapter; from gepa.optimize_anything import optimize_anything"` succeeds.
- Python SDK: `cd sdk/python && uv run --with pytest pytest test/` passes with renamed imports.
- Node SDK: `cd sdk/node && npm test` passes with renamed package.
- End-to-end: run `gepa-research discover` then `gepa-research optimize --max-metric-calls 10` against `tests/fixtures/tau3_demo/`; confirm at least one candidate is produced by gepa and backported into `.gepa-research/<run>/graph.json`; confirm the dashboard renders the new nodes.
- `python3 scripts/check_versions.py` passes (all manifests agree on version, all names updated).
- CI (`.github/workflows/ci.yml`) green on a test branch.

## Critical files

**Renamed/moved:**
- `plugins/evo/` → `plugins/gepa-research/` (whole tree)
- `plugins/gepa-research/src/evo/` → `src/gepa_research/`
- `sdk/python/src/evo_agent/` → `src/gepa_research_agent/`

**Modified heavily:**
- `plugins/gepa-research/src/gepa_research/core.py` — rename constants, prune subagent code
- `plugins/gepa-research/skills/optimize/SKILL.md` — rewrite around `optimize_anything`
- `plugins/gepa-research/pyproject.toml` — add `gepa` dep, rename package + scripts
- `plugins/gepa-research/bin/gepa-research`, `bin/gepa-research-version-check`
- `README.md`, `NOTICE`
- `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`
- `plugins/gepa-research/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`
- `.github/workflows/ci.yml`, `.github/workflows/publish.yml`
- `scripts/check_versions.py` and sibling shim scripts
- `tests/e2e.py`, `tests/unit/test_core.py`, fixture SDK imports

**Added:**
- `plugins/gepa-research/src/gepa_research/gepa_adapter.py`

**Deleted:**
- `plugins/gepa-research/skills/subagent/`

## Risks / gotchas

1. **Loss of parallelism.** Evo fans out 5 subagents per round in separate worktrees; Gepa is serial. Single-machine throughput drops. Mitigation: accept the tradeoff for this rebrand; revisit multi-instance Gepa orchestration later if needed.
2. **Reflection LM cost/config.** `optimize_anything` needs a reflection LM configured. `config.json` from `discover` must declare one (e.g., `reflection_lm: "claude-opus"`); add a default and document it.
3. **Graph-schema compatibility.** Existing `.evo/` state directories from before the rename won't migrate automatically — acceptable since this is a rebrand, but document it. Old dashboards expecting `.evo/` won't find state; a migration hint in the CLI is a nice-to-have.
4. **Node SDK unscoped name collision.** `gepa-research` on npm is claimed by nobody as of this writing, but worth verifying with `npm view gepa-research` before publishing. If taken, fall back to `@cyrusnuevodia/gepa-research`.
5. **Version-tag prefixes in `publish.yml`.** Tag prefixes (`v*`, `py-v*`, `node-v*`, `cli-v*`) are generic and don't need renaming, but the jobs they trigger must publish to the new package names.
6. **Banner image and docs site.** `assets/banner.png` still says "evo". Regeneration is out of scope for this plan; README alt text and title are updated but the raster is a follow-up.
