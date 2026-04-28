# plans/ — how this project was built

One plan, one method.

## The method: `/make` — Claude thinks, Codex builds

The user works in Claude Code. The driving skill is [`/make`](skills/make.md), which composes [`/shaping`](skills/shaping.md) (collaborative problem definition) and [`/build`](skills/build.md) (question-driven implementation guard) into a five-phase pipeline:

1. **Shape.** Lock requirements and design decisions with the human.
2. **Research.** Read-only oracle (Codex / subagent) investigates the codebase.
3. **Plan.** Decompose into non-overlapping, parallelizable workstreams.
4. **Execute.** Parallel write-mode agents per workstream. Claude never edits code itself.
5. **Verify.** Typecheck / lint / test / review. On failure, fix the prompt and re-dispatch — never patch the agent's output by hand.

The three SKILL.md files in [`skills/`](skills/) are the full text. Read `make.md` first.

## The plan (Phase 3 output)

[`one-shot.md`](one-shot.md) is the actual plan document Claude wrote during `/make`'s Plan phase on **2026-04-20**, exactly as captured before execution began. It defines essentially everything that became this repo:

- **Phase A** — mechanical rename `evo` → `gepa-research` across packages, manifests, CI, tests, fixtures.
- **Phase B** — replace the inner optimization loop with `gepa.optimize_anything`. Write the `GepaResearchAdapter` that bridges GEPA's candidate/evaluator protocol to gepa-research's git-worktree + benchmark-subprocess infrastructure.
- **Phase C** — verification.

It came from a single Claude Code session that started with a one-line prompt:

```
/make

@../gepa/docs/docs/blog/posts/2026-02-18-introducing-optimize-anything/

So I just cloned this project called Evo and I want to rename it to Gepa Research
and have it use the Gepa algorithm
```

The methodology expanded that into the artifact you see here.

## Why a plan and not full transcripts

The session that produced this plan ran for hours and spawned seven Explore subagents. Reading hour-long transcripts on GitHub — collapsed dropdowns of tool calls, intermediate results, dead ends — is hard. **The plan is the lesson.** It's where the methodology compresses hours of conversation into a structured, executable document. The user's lead prompt (above) plus the spawn prompts inside the plan's "Critical files" section is most of the prompting story.

## How to read this directory (humans)

1. [`skills/make.md`](skills/make.md) — the spine.
2. [`skills/shaping.md`](skills/shaping.md), [`skills/build.md`](skills/build.md) — the sub-skills `/make` invokes in Phase 1.
3. [`one-shot.md`](one-shot.md) — `/make` applied to the founding task.

## How to use this directory (AI agents)

If you're an agent and have been pointed here to replicate similar work:

1. Read the three skill files. The pipeline is non-optional — Claude thinks, Codex builds.
2. Read [`one-shot.md`](one-shot.md) as a worked example of the Plan phase output. Notice the structure: **Context → Intended outcome → Concrete changes (file-level) → Verification → Critical files → Risks**. Reproduce that structure in your own plans.
3. Apply the pipeline to your task. Compress your input prompt; let the methodology expand it. Pause to ask via `AskUserQuestion` rather than guessing.
4. Never hand-patch the builder's output. If a workstream fails verification, fix the prompt and re-dispatch.
