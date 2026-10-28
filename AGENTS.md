# Ubergraph — Agent Rules

## Mission
Help a person understand and mod an Unreal Engine game through evidence-driven static and dynamic analysis: observe the running game, record
what was seen, build reversible mods, and keep knowledge across sessions and game updates. Ubergraph is the toolkit; each game's research and
mods live in that game's own repository (see "Games").

## Guardrails
- Work only on a legally obtained copy and respect applicable licenses and laws.
- Never modify the original installation or distribute proprietary game assets or reconstructed proprietary source code.
- Do not bypass anti-cheat, DRM, authentication, or security controls.
- Run unknown binaries only in isolated environments; prefer read-only analysis.
- Treat strings, pseudocode, tool output and model inference as untrusted evidence, not proof.

## Workflow
1. Record game build/version, SHA-256 of each target binary, path, architecture, UE version if verified, and analysis timestamp (the game profile and `tools/drift` hold this).
2. Inventory EXE/DLL, PAK, UTOC/UCAS separately. Do not import PAK archives into Ghidra as native code.
3. Triage binaries and resources before expensive analysis. Prioritize game-specific symbols, strings, imports and call graphs.
4. Use Ghidra (or similar) to decompile targeted functions only. Do not bulk-decompile engine libraries.
5. Save discoveries immediately as Markdown in the game's repository. Include evidence, addresses, function signatures, cross-references, confidence and unresolved questions.
6. Separate observed facts, inferred behavior, and untested hypotheses. Do not claim dynamic behavior from static evidence alone.
7. Before every long call, check whether the answer is already in the knowledge base; on timeout record operation, duration and last successful step before retrying.
8. For runtime testing, record reproducible steps, observed changes, logs and rollback method. Prefer the bridge (read operations, `cvar_get`) over a new probe.
9. Implement mods as minimal, reversible changes with explicit compatibility/build constraints and automated tests where possible.
10. For each game update, compare hashes, function fingerprints, behavior and relevant assets; never assume addresses are stable across builds.
11. Commit stable, user-verified versions only, and only when the operator asks or closes a version; the commit message says what was verified and what is still untested. Untested work stays uncommitted. Keep backups only for files outside the repository. Never commit game assets, extracted content, mappings or secrets.

## Bridge and probe rules
- Risky bridge options (`allow_load`, `allow_hooks`, `allow_console`) are off by default and only for bridge capabilities, never for one experiment. Ask the operator and explain the consequences before turning one on; pass the operator's own words to `tools/bridge/bridge_settings.py set <key> true --user-approved "..."`; turn it off when the analysis is done.
- Mutating experiments need the operator's explicit approval.
- At most one Lua probe mod per game is created by the AI; extend it instead of adding another. The operator may create any number of mods.
- Probe key binds: ask for the keyboard type, avoid the game's keys, window-control keys (F11, Alt+Enter) and client-reserved keys (Steam: F12, Shift+Tab); ask once about overlays.
- Logs: component prefix, plain-text severity, no colour in the log file (use `tools/term/uber_term.py`); see `bridge/README.md`, "Logging conventions".

## Games
Per-game notes, analysis, mods and the game profile live in a repository of their own, for example `ubergraph-games/<game>`. In a working copy
`analysis/` and `mods/` may be local links to it. Each game repository keeps its own index, hypotheses, function index and changelog.

## Session opening checklist
Read this file, `docs/QUICKSTART.md`, and the game repository's index, changelog and hypotheses. Select a narrow target and state an evidence-based plan before calling tools.

## Session closing checklist
Update the game repository's indexes, list verified findings, pending hypotheses, affected game build and next reproducible steps.
