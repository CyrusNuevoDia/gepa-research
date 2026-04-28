---
skill: make
summary: 'Orchestrator: Claude thinks, Codex builds'
---

---
name: make
description: |
  Full-stack feature builder. Shapes requirements with the human via /shaping
  and /build, researches codebase with Codex, plans implementation, then
  orchestrates parallel Codex agents to write the code.
  Claude thinks, Codex builds.
---

# Make

Claude elicits. Codex researches. Claude plans. Codex builds. Claude verifies.

## Roles

| Role | Actor | Purpose |
|------|-------|---------|
| Elicitor | Claude + Human | Shape requirements, resolve ambiguity |
| Oracle | Codex (read-only) | Research codebase, gather context |
| Planner | Claude | Decompose into parallelizable workstreams |
| Builder | Codex (full-auto) | Write the code |
| Verifier | Claude | Tests, lint, typecheck, review |

## Phase 1: Shape

Invoke sub-skills to collaboratively define the problem and solution with the human.

### Step 1: Shape the solution

Use the Skill tool to invoke `/shaping`. Work with the human to:
- Define requirements (R0, R1, R2...)
- Explore solution shapes (A, B, C...)
- Run fit checks
- Select and detail a shape
- Breadboard into concrete affordances

### Step 2: Lock in implementation decisions

Use the Skill tool to invoke `/build`. Work with the human to:
- Surface remaining questions one at a time
- Provide recommendations with confidence levels
- Lock in each decision before moving to the next
- Resolve all ambiguity

**Exit criteria:** A shaped pitch with clear requirements, a selected shape, and zero open questions.

## Phase 2: Research

Dispatch Codex as a read-only oracle to research the codebase itself. Codex can discover files on its own — Claude does not pre-gather paths or embed file contents.

### Invoke the Oracle

```bash
bunx @openai/codex exec \
  --sandbox read-only \
  -c 'model_reasoning_effort="xhigh"' \
  -m gpt-5.4 \
  "<research prompt>"
```

**Timeout:** Pass `timeout: 3600000` (60m) when calling the Bash tool. Codex with xhigh reasoning can take well over 10 minutes on large contexts.

The research prompt must include:
1. The shaped requirements from Phase 1 (summarized)
2. Specific questions: existing patterns to reuse, types to extend, entry points to hook into, gotchas
3. An instruction to return a structured report that Phase 3/4 can feed directly into Builder Codex prompts

The oracle's report must include, for each relevant area:
- **File paths** (absolute or repo-relative) — the exact files Builders will need
- **Excerpts** — the specific functions, types, or blocks Builders should see, quoted inline
- **Patterns to reuse** — named conventions with a pointer to a canonical example
- **Gotchas** — invariants, ordering constraints, or non-obvious coupling

The shape of this report matters: Claude will paste chunks of it verbatim into Builder prompts, so it should be copy-paste-ready rather than prose.

### Summarize findings

Present the oracle's analysis to the user. Highlight:
- Existing patterns and utilities to reuse
- Types and schemas to extend
- Entry points to hook into
- Potential gotchas or conflicts

## Phase 3: Plan

Decompose the implementation into independent, parallelizable workstreams.

### Workstream spec

Each workstream must define:

| Field | Description |
|-------|-------------|
| **Scope** | What this workstream builds (1-2 sentences) |
| **Files** | Exact files to create or modify |
| **Context** | Paths, excerpts, and patterns from the Phase 2 oracle report that this workstream needs |
| **Standards** | Coding patterns and conventions to follow |
| **Success** | How to verify this workstream is correct |

### Conflict prevention

**Workstreams MUST touch non-overlapping files.** If two workstreams need to modify the same file, they must run sequentially — mark the dependency explicitly.

Before dispatching, validate:
- No two parallel workstreams share a file
- Sequential dependencies are ordered correctly
- Each workstream is self-contained (has all context it needs)

### Present plan to user

Show the workstream breakdown and ask for approval before dispatching. The user must see:
- How many workstreams and which are parallel vs sequential
- What each workstream does
- Which files each touches

## Phase 4: Execute

Dispatch Codex agents to implement each workstream.

### Codex execution command

```bash
bunx @openai/codex exec \
  --sandbox workspace-write \
  -c 'model_reasoning_effort="xhigh"' \
  -m gpt-5.4 \
  "<workstream prompt>"
```

Valid `--sandbox` values are `read-only`, `workspace-write`, and `danger-full-access`. `workspace-write` is the right default for Builders (write access inside the workspace, no arbitrary system access). Use `danger-full-access` only if a workstream legitimately needs to touch things outside the repo.

**Timeout:** Pass `timeout: 3600000` (60m) when calling the Bash tool. Build workstreams with xhigh reasoning routinely exceed 10 minutes.

### Workstream prompt template

The prompt to each codex agent must include:

1. **Task** — What to build (from workstream scope)
2. **Context** — Relevant file contents embedded via `$(cat ...)`
3. **Standards** — Coding conventions from CLAUDE.md (no semicolons, Biome, arrow functions, etc.)
4. **Constraints** — Files this agent may touch (nothing else), patterns to reuse
5. **Success criteria** — What "done" looks like

### Dispatch strategy

- **Independent workstreams** — Launch in parallel using Bash tool with `run_in_background`
- **Sequential workstreams** — Wait for dependencies to complete before dispatching
- **Monitor** — Collect output from each agent as it completes

### If a workstream fails

1. Read the error output
2. Diagnose: missing context? wrong file? bad assumption?
3. Re-dispatch with corrected prompt — do NOT fix it manually

## Phase 5: Verify

After all codex agents complete, Claude verifies the full integration.

### Verification checklist

Run these in order:

1. **Typecheck** — `bunx tsc --noEmit`
2. **Lint** — `bun run lint`
3. **Format** — `bun run fmt`
4. **Test** — `bun test`
5. **Review** — Read all changed files, check for quality and integration issues

### Handling failures

- **Type errors** — Re-dispatch a codex agent with the error context and affected files
- **Lint/format** — Run `bun run fmt` to auto-fix, only re-dispatch if structural issues
- **Test failures** — Re-dispatch with test file + implementation file + error output
- **Quality issues** — Re-dispatch with specific feedback

### Done

Present the user with:
- Summary of what was built
- Files created or modified
- Verification results
- Any remaining concerns

## Notes

- **Claude never writes code.** Only Codex writes code. Claude orchestrates, verifies, and re-dispatches.
- **Context quality matters.** The better the prompt, the better the output. Invest time in Phase 2.
- **Parallelism is the point.** The whole reason to decompose into workstreams is to run them concurrently.
- **Re-dispatch, don't patch.** If codex output is wrong, fix the prompt and re-run — don't manually edit.
