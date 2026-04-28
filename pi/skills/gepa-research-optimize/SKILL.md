---
name: gepa-research-optimize
description: Run the GEPA-backed optimization loop from Pi for an initialized GEPAResearch workspace. Use after discovery when the user asks to optimize, continue a GEPAResearch run, raise the metric-call budget, or tune stall/reflection-lm settings.
argument-hint: "[max-metric-calls=N] [stall=N] [reflection-lm=MODEL]"
---

# GEPAResearch Optimize for Pi

This is the Pi-friendly entry point for GEPAResearch optimization. It exists because Pi skill commands are not package-namespaced.

## Procedure

1. Resolve `../../../plugins/gepa-research/skills/optimize/SKILL.md` relative to this `SKILL.md`, then read it completely.
2. Follow that canonical skill exactly, with these Pi conventions:
   - User-facing invocation is `/skill:gepa-research-optimize`.
   - The companion Pi extension prepends `plugins/gepa-research/bin` to `PATH`, so `gepa-research` and `gepa-research-version-check` should resolve inside Pi's bash tool when `uv` is installed.
   - If the wrapper commands still do not resolve, tell the user to install the CLI once with `uv tool install "git+https://github.com/CyrusNuevoDia/gepa-research#subdirectory=plugins/gepa-research"`, then re-run `/skill:gepa-research-optimize`.
3. Treat any arguments after `/skill:gepa-research-optimize` as the optional optimize parameters for the canonical optimize skill.
