---
name: gepa-research-discover
description: Initialize GEPAResearch for the current repository from Pi by loading the canonical discover workflow, constructing or wiring a benchmark, creating the baseline worktree, and running the first experiment. Use when the user asks to set up GEPAResearch, run discovery, or start a new optimization run.
argument-hint: <optional context about what to optimize>
---

# GEPAResearch Discover for Pi

This is the Pi-friendly entry point for GEPAResearch discovery. It exists because Pi skill commands are not package-namespaced.

## Procedure

1. Resolve `../../../plugins/gepa-research/skills/discover/SKILL.md` relative to this `SKILL.md`, then read it completely.
2. Follow that canonical skill exactly, with these Pi conventions:
   - User-facing invocation is `/skill:gepa-research-discover`.
   - The companion Pi extension prepends `plugins/gepa-research/bin` to `PATH`, so `gepa-research` and `gepa-research-version-check` should resolve inside Pi's bash tool when `uv` is installed.
   - If the wrapper commands still do not resolve, tell the user to install the CLI once with `uv tool install "git+https://github.com/CyrusNuevoDia/gepa-research#subdirectory=plugins/gepa-research"`, then re-run `/skill:gepa-research-discover`.
3. Treat any arguments after `/skill:gepa-research-discover` as the optional optimization context for the canonical discover skill.
