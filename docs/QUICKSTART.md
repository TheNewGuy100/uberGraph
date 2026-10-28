# Ubergraph quickstart

From nothing to "I can read the running game" in about ten minutes, then the path to a first mod. Every command is run from the repository
root. Status: **alpha**; the steps below were exercised on one game (see the end of this page for what is not proven).

## What you need

| For | You need |
|---|---|
| Reading a running game (bridge, terminal) | The game on Windows with [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) installed (tested with 3.0.1), Python 3.10+. |
| Lua tests | Node.js; `cd tools/lua-check && npm install` (luaparse for syntax, fengari to run the tests in a Lua VM). |
| Authoring and cooking mods | The matching Unreal editor (the same engine version as the game), the C++ toolchain it needs (MSVC), [`retoc`](https://github.com/trumank/retoc), and the game's `.usmap` mapping file (kept local, never committed). |
| Reading Blueprint bytecode | .NET SDK, and a read-only extraction of the game's containers. |

## 1. Write the game profile

A profile tells every tool where the game is and what it may write. Copy the example, fill in the real paths, and keep the copy local
(`*.local.json` is ignored by git):

```bash
cp profiles/the-last-caretaker.example.json profiles/my-game.local.json
python tools/profile/game_profile.py my-game          # prints the profile; placeholders such as <...> are reported as missing
```

The fields that matter first: `ue4ss.dir`, `game` (install root, executable, Steam app id), `deploy.allowedPaths` (the only places the
tools may write, for example `<ue4ss>/Mods/[uberGraph] */` and `<ue4ss>/Mods/shared/UberGraphLog/`) and `deploy.backupDir`. Field-by-field
notes: [GAME-PROFILES.md](GAME-PROFILES.md).

Record a baseline and check for drift whenever the game updates:

```bash
python tools/drift/check_drift.py my-game --record    # writes missing baselines (build id, executable hash, container sizes)
python tools/drift/check_drift.py my-game             # 0 = no drift, 1 = the game changed, 2 = nothing could be compared
```

## 2. Install the bridge

```bash
python tools/bridge/install_bridge.py install              # dry run: prints what would be copied
python tools/bridge/install_bridge.py install --apply      # copies [uberGraph] Bridge and the Lua libraries, with backup, hash check and log
python tools/bridge/bridge_settings.py init                # writes settings.txt with every risky option off
```

Start (or restart) the game and load a save. The bridge writes a heartbeat once per second.

```bash
python tools/bridge/bridge_client.py health                # heartbeat age, nothing sent
python tools/bridge/bridge_client.py ping                  # version, uptime
python tools/bridge/bridge_client.py find_all PlayerController
python tools/bridge/bridge_client.py describe_class object:pawn 50
python tools/bridge/bridge_client.py cvar_get r.ScreenPercentage
```

In Git Bash, arguments that start with `/` are rewritten by the shell; run commands with `/Script/...` or `/Game/...` paths from PowerShell
(or set `MSYS_NO_PATHCONV=1`).

## 3. Watch the log and talk to the bridge

```bash
python tools/term/uber_term.py                 # follows UE4SS.log, classified and coloured (the file stays plain text)
python tools/term/uber_term.py --repl          # also opens a prompt: ping, cvar NAME, console COMMAND, any bridge operation
python tools/term/uber_term.py --once --only bridge,probes --level warn
```

## 4. Risky options (off by default)

Three operations change the running game and are disabled until the operator turns them on: `load_asset` (`allow_load`), `watch_function`
(`allow_hooks`) and `console_exec` (`allow_console`). Each option's consequences are written next to it in `settings.txt` and in
[`bridge/README.md`](../bridge/README.md). The settings tool refuses to turn one on without the operator's own words, applies the change
through the deploy tool and logs it:

```bash
python tools/bridge/bridge_settings.py set allow_console true --user-approved "what the operator said"
python tools/bridge/bridge_settings.py set allow_console false
```

**AI agents:** ask the operator and explain the consequences first; never turn an option on for a single experiment.

## 5. A first mod

1. **Probe, then build.** Read the system you want to change with the bridge. Write down what you saw (facts, not guesses) in the game's own
   repository.
2. **A Lua mod** goes in your game repository's `mods/<name>/Scripts/main.lua` with an empty `enabled.txt`. Use the shared logger:
   `local log = require("UberGraphLog").new("[you] mymod")`. Install it with `python tools/deploy/deploy.py copy mods/<name> --to <ue4ss>/Mods --check-drift --apply`
   (dry run without `--apply`; undo with `deploy.py restore`).
3. **Cooked assets** (items, Blueprints, data assets): generate editor-side stand-ins of the game's native classes from the mapping
   (`python tools/usmap/gen_stubs.py --out <plugin folder> ClassA ClassB`), author in the editor with `tools/ue-editor` scripts, then
   `python tools/cook/cook_and_pack.py --container zMyMod_P --package /Game/MyMod/Thing --filter Thing` (cook, convert, verify, scan for
   forbidden references, optional deploy). The game must be closed to replace a container. The pipeline and its pitfalls:
   [COOKED-ASSET-PIPELINE.md](COOKED-ASSET-PIPELINE.md), [UE-EDITOR-AUTOMATION.md](UE-EDITOR-AUTOMATION.md).

## 6. Run the tests

```bash
python tools/deploy/test_deploy.py
python tools/drift/test_drift.py
python tools/term/test_uber_term.py
python tools/term/test_uber_repl.py
cd tools/lua-check && npm install && npm test        # logger and bridge behaviour in a Lua VM; also: node check-lua.js <files> for syntax
```

## What is not proven yet

- A second game: everything above was done on one game, one engine version (UE 5.8) and one UE4SS version (3.0.1).
- A full run after a game update (the drift tool detects the change; the follow-up flow was not exercised).
- A fresh installation by someone who is not the author: the prerequisites above are the real ones, but there is no CI and no automated
  installer for them.
- Native crashes cannot be caught from Lua; a mod that crashes the game does so without a message. Keep experiments small.
