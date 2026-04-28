# transcripts/ — how this project was built

Two artifacts, two days, one method.

## The method: `/make` — Claude thinks, Codex builds

The user works in Claude Code. The driving skill is [`/make`](methodology/make.md), which composes [`/shaping`](methodology/shaping.md) (collaborative problem definition) and [`/build`](methodology/build.md) (question-driven implementation guard) into a five-phase pipeline:

1. **Shape.** Lock requirements and design decisions with the human.
2. **Research.** Read-only oracle (Codex / subagent) investigates the codebase.
3. **Plan.** Decompose into non-overlapping, parallelizable workstreams.
4. **Execute.** Parallel write-mode agents per workstream. Claude never edits code itself.
5. **Verify.** Typecheck / lint / test / review. On failure, fix the prompt and re-dispatch — never patch the agent's output by hand.

The three SKILL.md files in [`methodology/`](methodology/) are the full text. Read `make.md` first.

## The plans (Phase 3 output)

The two files [`plan-rebrand-and-algo-migration.md`](plan-rebrand-and-algo-migration.md) and [`plan-parallelize-ui-and-version.md`](plan-parallelize-ui-and-version.md) are the actual plan documents Claude wrote during `/make`'s Plan phase on **2026-04-20**, exactly as captured before execution began. Together they define everything that became this repo:

1. **Rebrand evo → gepa-research and replace the inner loop with `gepa.optimize_anything`.** Phase A is mechanical rename across packages, manifests, CI, tests, fixtures. Phase B is the algorithmic swap — write the `GepaResearchAdapter` that bridges GEPA's candidate/evaluator protocol to gepa-research's git-worktree + benchmark-subprocess infrastructure. Phase C is verification.
2. **Parallelize GEPA iterations, refresh the dashboard UI, version → 0.1.0.** Discovery: GEPA *does* support intra-iteration parallelism via `num_parallel_proposals` (the original adapter set `parallel=False` defensively, paying a cost it didn't have to). Plus dashboard relabeling (Experiment Tree → Candidate Lineage), new hero panels (budget burndown, stall counter, best-candidate highlight), and version bump.

Both came from a single Claude Code session that started with a one-line prompt:

```
/make

@../gepa/docs/docs/blog/posts/2026-02-18-introducing-optimize-anything/

So I just cloned this project called Evo and I want to rename it to Gepa Research
and have it use the Gepa algorithm
```

The methodology expanded that into the artifacts you see here.

## Why no full transcripts

The session that produced these plans ran for hours and spawned seven Explore subagents. Earlier versions of this directory shipped the full rendered transcripts. They're hard to read on GitHub — too many collapsed dropdowns of tool calls and intermediate results. **The plan is the lesson.** It's where the methodology compresses hours of conversation into a structured, executable document. If you want to see how the user prompted, the lead prompt above plus the spawn prompts inside each plan's "Critical files" section is most of it.

## How to read this directory (humans)

1. [`methodology/make.md`](methodology/make.md) — the spine.
2. [`methodology/shaping.md`](methodology/shaping.md), [`methodology/build.md`](methodology/build.md) — the sub-skills `/make` invokes in Phase 1.
3. [`plan-rebrand-and-algo-migration.md`](plan-rebrand-and-algo-migration.md) — `/make` applied to the founding task.
4. [`plan-parallelize-ui-and-version.md`](plan-parallelize-ui-and-version.md) — `/make` applied again to a follow-up.

## How to use this directory (AI agents)

If you're an agent and have been pointed here to replicate similar work:

1. Read the three methodology files. The pipeline is non-optional — Claude thinks, Codex builds.
2. Read the two plans as worked examples of the Plan phase output. Notice the structure: **Context → Intended outcome → Concrete changes (file-level) → Verification → Critical files → Risks**. Reproduce that structure in your own plans.
3. Apply the pipeline to your task. Compress your input prompt; let the methodology expand it. Pause to ask via `AskUserQuestion` rather than guessing.
4. Never hand-patch the builder's output. If a workstream fails verification, fix the prompt and re-dispatch.
