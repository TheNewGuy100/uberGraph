# Changelog

Format: newest first. A release lists what was verified and what was not. See [docs/RELEASE-FLOW.md](docs/RELEASE-FLOW.md).

> **History note (2026-10-28):** versions 0.1.0, 0.1.1 and 0.1.2 below were developed before the repository was published. The public history starts at one clean commit tagged `v0.1.2` that contains all of them; the entries are kept as the record of what each step added and verified.

## 0.1.2 (alpha), neutral example project

The bridge is unchanged (v0.1.3, protocol 1).

**Changed** the authoring project is now `unreal/example` (`ExampleProject`) and its editor plugin is `UbergraphEditorTools` (`UUbergraphLayoutLibrary`), with neutral names, a generic engine association (`5.8`), a fresh project id and no game-specific plugin entry or map. `unreal/example/README.md` explains how to copy and rename it. The first game's own authoring project (with its real `Content/`) stays on the author's disk, git-ignored. `cook_and_pack.py` refuses cooked packages that reference either module family; `dump_layouts.py` tries the new plugin name first and the old one second; the example profile points at `unreal/example`.

**Verified** `tools/test_all.py` passes (8 steps); the example project builds with Unreal Build Tool (`ExampleProjectEditor Win64 Development`, 13 steps, succeeded, editor closed).
**Not verified** loading the example in the editor and calling `UbergraphLayoutLibrary` from Python (`dump_layouts.py`) against it; the first game's own project was not rebuilt with the renamed plugin, so it keeps the old plugin name.

## 0.1.1 (alpha), documentation

Documentation only; the bridge is unchanged (v0.1.3, protocol 1).

**Added** the flow diagram in the README ("How it fits together"), with the text diagram kept as a collapsible block.

**Verified** `tools/test_all.py` passes (8 steps); the diagram's commands and file names were checked against the code (`uber_term.py --repl`, `ping`, `cvar`, `console`, `settings`, `.utoc/.ucas/.pak`).
**Not verified** how the README renders on GitHub; one line of the diagram's terminal panel has a garbled word (`WARN ... Inventory_PlayerBox_Large_C` should read `WARN no BP_Inventory_PlayerBox_Large_C in the world`). The manual `hmg` checks against a game were not repeated for a documentation-only change.

## 0.1.0 (alpha), first Ubergraph version

Bridge `[uberGraph] Bridge` v0.1.3 (protocol 1).

**Added**
- Bridge: read operations (`ping`, `status`, `find_all`, `get`, `describe_class`, `get_array`, `read`, `find_object`, `scan`, `map_info`, `probe_methods`, `map_peek`, `describe_function`), `cvar_get`, and three off-by-default risky operations (`load_asset`, `watch_function`, `console_exec`) with their settings, consequences text and approval log.
- Tools: game profile, deploy with backup/hash/log/undo and allowed paths, build drift check, cook-and-pack pipeline, `.usmap` tools and stand-in generator, Blueprint bytecode dumper, editor automation scripts, terminal (`uber_term.py`, `--repl`) and the Lua logger `UberGraphLog`.
- Tests: Python unit tests (deploy, drift, terminal, prompt) and Lua VM tests (bridge, logger); `tools/test_all.py` runs the gate.
- Documentation: README with logo, configuration and FAQ; quickstart, game profiles, cooked asset pipeline, editor automation, UE4SS Lua notes, release flow.
- Licence: MIT with the Commons Clause condition (free use, modification and redistribution with credit; no selling), in `LICENSE`.

**Verified (on one game, one machine)** authoring in the editor, cook, load in the game and registration in the game's menu; the bridge on a running game; the terminal on a real log; the logger in the game.

**Not verified** a second game; a run after a game update; installation by someone else; CI.

**Known debt** a few analysis tools under `tools/` have game-specific defaults; the previous git history of this repository still contains the first game's research notes (they now live in a separate repository).
