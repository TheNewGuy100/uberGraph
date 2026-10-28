# [uberGraph] Bridge (v0.1.3)

A development bridge for UE4SS games, read-only by default with explicitly gated optional operations. **Development use only; never ship it to players.** A client writes a request file, the mod runs it on the game thread and writes a response file. No code from the request is ever executed: requests are plain `key=value` lines, responses are JSON written by the mod.

## Safety rules built in

- Default operations are read-only; asset loading and observe-only hooks need separate settings and the user's approval. No eval and no value overrides: **bridge settings are for bridge capabilities only, never for a single experiment**. Experiments that change the game live in their own mods (for example `mods/VanillaPlusDetachTagProbe`), not in the bridge.
- Everything on the game thread (`ExecuteInGameThread`); the polling thread only touches files.
- Nothing is kept between requests: objects are found again by name each time. A cached `UObject` was garbage collected and crashed the game in an earlier project.
- Soft-pointer properties are never read (they crash UE4SS's property reader in other projects).
- One request at a time; request file capped at 8 KB; request ids must be 8 to 32 letters or digits.
- A breadcrumb (`io/lastop.log`) is written before each operation, so after a crash the last request is known. `io/heartbeat.txt` is refreshed every second.

## Protocol (version 1)

Request, `io/request.txt`:

```
id=<8-32 letters/digits>
op=<ping|status|find_all|get>
arg.<name>=<value>
```

Response, `io/response.json`: `{"id": ..., "protocol": 1, "ok": true|false, "op": ..., "result": {...} | "error": "..."}`.

| op | args | result |
|---|---|---|
| `ping` | none | version, uptime |
| `status` | none | world, player controller, pawn (full names) |
| `find_all` | `class`, `limit` (default 20, max 200) | count, returned, truncated, items (full names) |
| `describe_class` | `class` (a path like `/Script/Voyage.VoyageSkill`) or `object`; `limit` (default 100); `functions=false` | own properties (name, type) and function names of each class up the chain, stopping at `UObject` |
| `get_array` | `object`, `property` (must be an `ArrayProperty`), `limit` (default 50) | count, returned, truncated, items |
| `read` | `object` (also `cdo:/Script/Mod.Class`), `property`, `depth` (default 2, max 4), `limit` (default 20, max 100) | typed value: structs expanded by reflection, arrays, enum name + number; maps and sets skipped |
| `find_object` | `path` | found, full name, class, outer |
| `load_asset` | `path` (a `/Game/` object path) | needs `allow_load=true` in `settings.txt`; see "Optional operations" |
| `describe_function` | `path` (`/Game/.../Pkg.Class_C:Function`) | parameters (name, type) and flags; read-only |
| `cvar_get` | `name` | reads a console variable (float, int and bool readings through the engine's own getters); read-only |
| `console_exec` | `command` | runs ONE allow-listed console command; needs `allow_console=true`; see "Optional operations" |
| `watch_function` | `action` (start / log / stop / list), `path` | observe-only hook; needs `allow_hooks=true`; see "Optional operations" |
| `scan` | `contains` and/or `class`, `limit` | matches, visited, elapsed_ms, items; stops working after 2 s |
| `get` | `object` (`pc`, `pawn`, `pcm`, `world`, or a path / full name), `property` (comma list, max 8) | for each property: type and value, or `error` / `skipped` |

## Install and use

```
python tools/bridge/install_bridge.py install --apply     (backup + hash + log through tools/deploy)
python tools/bridge/bridge_client.py health
python tools/bridge/bridge_client.py ping
python tools/bridge/bridge_client.py get pawn BaseEyeHeight
python tools/bridge/install_bridge.py uninstall --apply
```

The bridge enables itself with its own `enabled.txt`; `mods.txt` is not edited. Restart the game after installing.

## Status

First run, 2026-10-26, user-run: `ping`, `status`, `find_all VoyageSkill 3` (211 skills, same count as the registry probe) and `get pawn BaseEyeHeight,JumpMaxCount` worked; the last returned **64** and **1**, equal to the key probe. The next request, `get pawn CharacterMovement,NoSuchProp`, **crashed the game** (`EXCEPTION_ACCESS_VIOLATION` reading `0x40` inside UE4SS code, 69 s after start). The breadcrumb `io/lastop.log` named that exact request, which is what it is for.

Cause (hypothesis, not proven): looking up a property that does not exist walked up the class chain past the top, where `GetSuperStruct()` returns an invalid wrapper instead of nil, and `ForEachProperty` was called on it. The first successful reads never reached that point because the property was found earlier in the chain. Fixed in the script (`IsValid` check on each class, stop at `UObject`) and reinstalled. **Re-run by the user the same day: the same request now returns `property not found` for the missing name and the object for `CharacterMovement` (`VoyageCharacterMovementComponent`), with no crash**; a bad object path and an unknown op return clean errors. One run only, so the cause stays a hypothesis that the fix is consistent with.

Known limits of v0.1: struct values are not expanded (`ViewTarget` comes back as the struct's type name, not its fields); arrays and maps are not read; a path starting with `/` must not be passed through Git Bash (it rewrites it to `C:/Program Files/Git/...`); use PowerShell.

Syntax checked with `tools/lua-check`.

## Optional operations (off by default)

### `load_asset`: loads a game asset by path (disabled until `allow_load=true`)

`load_asset path=/Game/.../Asset.Asset` asks the game to load an asset from **its own containers** so that `describe_class`, `read`, `get` and `cdo:` can inspect classes that the current map has not loaded. Returns whether it was already loaded, whether it loaded, its class, the generated Blueprint class if any, and the time taken. Only `/Game/` paths, one per request. It is **off by default**: the mod reads `settings.txt` (in the mod folder; a missing file or key means off) on every use, so turning it on needs no restart.

**Consequences (what an agent must tell the user before asking):** it changes the game's in-memory state. The game thread can pause while the asset and its dependencies (meshes, materials, other Blueprints) load; memory use goes up (the author's PC has hit its commit limit before); the asset's `PostLoad` logic runs; a strange asset could crash the game. Nothing is written to disk, and the bridge does not keep the loaded objects (the game may unload them later). Assets from our own extra containers need a different technique and are not covered.

**Rule for AI agents:** this function exists and an agent may enable it, but **it must first ask the user and explain the consequences above**, then use `tools/bridge/bridge_settings.py set allow_load true --user-approved "<the user's own words>"`. The tool refuses without an approval text, applies the change through `tools/deploy` (allowed paths, backup, hash, log) and records the approval in `<backupDir>/bridge-settings-log.jsonl`. Ask again for a new session or a new purpose; one approval does not cover other operations. Turn it off again with `set allow_load false` when the analysis is done.

Approval on record: the user authorized turning it on during this project's session of 2026-10-26 ("pode escrever ... eu autorizo voce a ligar ela"), for read-only analysis of game assets, one at a time.

### `watch_function`: observe-only hook on one game function (disabled until `allow_hooks=true`)

`watch_function action=start path=/Game/Dir/Pkg.Class_C:Function` places a pre and post hook that only records, in a ring buffer of 50 strings, the object name the function ran on and its primitive arguments or return value; `action=log` reads them, `stop` removes the hook, `list` shows active ones. At most 3 at a time. `describe_function path=...` (read-only, always available) shows a function's parameters and flags first.

**Consequences (what an agent must tell the user before asking):** the hook runs inside the game every time the function is called, so a frequently called function costs performance; hooks have been a crash suspect in earlier projects (a hook on every actor was never ruled out); the hook goes away when the game closes or with `stop`. It stores strings only, keeps no `UObject` and changes nothing.

**Same rule as `load_asset`:** off by default; an agent must ask the user and explain these consequences, then use `tools/bridge/bridge_settings.py set allow_hooks true --user-approved "<the user's words>"` (refused without an approval text, applied through `tools/deploy`, logged). Approval on record (2026-10-26): after the consequences were explained, the user said they would let the agent run its test ("vou deixar voce fazer seu teste"), for the observe-only `CanThisUnWeld` test only; the settings tool logged it. Turn it off again after that test.

### `console_exec`: one console command (disabled until `allow_console=true`)

`console_exec command="r.Shadow.MaxResolution 1024"` runs one console command through `KismetSystemLibrary:ExecuteConsoleCommand`. Only commands whose first word is `stat`, `log`, `obj`, `showflag`, `dumpconsolecommands`, `listtimers`, or a cvar starting `r.`, `sg.`, `t.` run; no `;`, `|` or control characters; quit/open/travel commands are refused. Read a variable back with `cvar_get`.

**Consequences (what an agent must tell the user before asking):** it changes the running game (a console variable, a stat overlay, a log category) until the game closes or the value is set back; a wrong value can make the game slow, unstable or ugly. The console's output text is not returned (the engine does not expose it to Lua); only the effect is observable (`cvar_get`, the UE4SS log).

**Same rule as the other risky options:** off by default; an agent must ask the user and explain these consequences, then use `tools/bridge/bridge_settings.py set allow_console true --user-approved "<the user's words>"`. Turn it off again when the test is done.

## Rules for probe mods (AI agents)

- At most **one** Lua probe mod per game is created by the AI; extend it instead of adding another. The operator may create any number of mods.
- Probe key binds: ask the operator for the keyboard type first (an 80% keyboard has no numpad) and do not rely on the numpad by default; never bind keys the game uses, window-control keys (F11, Alt+Enter) or keys reserved by the game client (Steam: F12 screenshots, Shift+Tab overlay); ask once whether overlays (Steam, Discord, GPU vendor, recorders) could conflict and record the answer in the game profile notes.
- Prefer the bridge (read operations, `cvar_get`, `console_exec` after asking) over a new probe; remove concluded probes from the game folder.

## Logging conventions (AI agents)

- **Prefix every line** with the component: `[uberGraph] bridge: ...`, `[uberGraph] Probes/<section>: ...`. It is what the agent greps for.
- **Severity as plain text**, greppable and free of control characters: start the message with `INFO`, `WARN` or `ERROR` only when the level matters (for example `[uberGraph] Probes/chest: WARN no pawn`). Default is no level word.
- **UE4SS may style levels itself** (a background colour for its own warnings and errors in the console window). That styling is the console's; the log file keeps plain text. Do not depend on it, and do not try to reproduce it.
- **Colour (ANSI escape codes) is optional and rare.** Use it only for one specific detail the operator must not miss, never for whole lines or routine output. It is untested in this game: the console window may or may not interpret it, and the GUI console (ImGui) probably shows it as broken text.
- **Before keeping any colour, check it does not hurt agent reading:** print one coloured line, then search the log for the escape character (`grep -c $'' UE4SS.log`). If the file now holds escape characters, remove the colour. Control characters make logs noisier to read and waste context on useless characters, so a coloured line is only kept when the count of escape characters stays small and the operator confirms it helps.
- **Use the shared logger in Lua mods:** `local Log = require("UberGraphLog"); local log = Log.new("[uberGraph] Probes/chest")`, then `log.info(...)`, `log.warn(...)`, `log.error(...)` and `log.try(label, fn, ...)`. It adds the prefix and the level word and removes ANSI escape sequences and control characters from every message. Source: `lua/shared/UberGraphLog/UberGraphLog.lua`; `tools/bridge/install_bridge.py install --apply` copies it to `<ue4ss>/Mods/shared/UberGraphLog/`. Mods should fall back to plain prints if the module is missing (see `mods/VanillaPlusProbe`). The bridge keeps its own one-line logger so it stays installable alone.
- **ASCII only** in banners and logs (see the ASCII art note: plain spaces, no tabs, no box-drawing characters).

**Terminal:** `python tools/term/uber_term.py` follows the UE4SS log of the profile and shows it classified and coloured (component, level, `--only`, `--level`, `--grep`, `--once`). The colour exists only on the screen of whoever runs it; the log file stays plain text, so reading it with `grep` is unaffected. With `--repl` it also opens a prompt (`uber> `) that sends commands to the bridge (`cvar NAME`, `console COMMAND`, `ping`, any bridge operation, `settings` read-only); the bridge itself refuses risky operations while their option is off, and the prompt never turns an option on. Tests: `python tools/term/test_uber_term.py`. and `python tools/term/test_uber_repl.py`.

## History

v0.1.1 (2026-10-27) briefly carried an experiment-specific `unweld_test` operation (a temporary `CanThisUnWeld` false override for one actor; result in `analysis/NEW-CONTAINER-DESIGN.md`). It was removed in v0.1.2 because bridge settings are not meant for single experiments; the code is archived in `analysis/artifacts/container-weld-20261027/unweld-test-op-bridge-v0.1.1.lua`.

## Credits

Ideas (file polling on the game thread, a breadcrumb file before each operation, skipping soft-pointer reads, read-only mode, re-resolving objects by name) come from reading the READMEs and code of [ue4ss-bridge](https://github.com/littleRabbit94/ue4ss-bridge) (MIT) and [unreal-vibe-modding](https://github.com/glitchbunny0/unreal-vibe-modding) (MIT). No code was copied. See `../CREDITS.md`.

## Run log

- 2026-10-26 (user restarted the game): `describe_class object:pawn` returned the class chain `BP_FirstPersonCharacter_New_C` > `BP_Base_Character_C` > `VoyageCharacter` ...; `describe_class /Script/Voyage.VoyageSkill` returned `Unlock` (struct), `Items` (array), `Icon`, and the base data asset members; a nonexistent class and a non-array property returned clean errors; `get_array` on `DA_Skill_Engineering_FortiHold_Storage_Container` `Items` returned 1 element, `DA_Item_PlayerBoxLarge`, matching the item recorded from the package parse. No crash, game alive afterwards. One run only.
- 2026-10-26 (second restart): `find_object` found `DA_Item_PlayerBoxLarge` (class `VoyageItem`) and returned `found: false` for a missing path. `read` of the FortiHold skill's `Unlock` returned `Cost` 1, `Requirement` 11 and `UnlockMethod` 2 with the enum name `EVoyageSkillUnlockMethod::Tier`, matching the values read earlier by key probe. `read pcm ViewTarget` expanded a nested struct three levels (`POV`: `FOV` 120, `Location`, `Rotation`, ...). A `MapProperty` came back as skipped, a missing property and a missing class (`cdo:`) gave clean errors, and the CDO of `VoyageSkill` read `UnlockMethod` `Unknown` (0). `scan` visited about 226,000 objects in about 1 s (a one-second game-thread pause per scan) and found 2 objects for `FortiHold` and 4 `VoyageItem` assets with `PlayerBox` in the name, including `DA_Item_PlayerBoxSmart`, which is not in our earlier notes. No crash. One run each.
- Bug seen in that run: boolean fields that are `false` showed as `{"error": "false"}` (an `ok and X or Y` idiom turning a false value into the error branch), and null object pointers showed as `<userdata>`. Fixed in the script (explicit branch; null objects reported as `null_object`, other unreadable values as `unreadable` with the property type) and reinstalled; **not yet re-run**.
- 2026-10-26 (third restart): the fixes worked. `read pcm ViewTarget` now shows `false` booleans correctly (`bConstrainAspectRatio` false, `bUpdateOrthoPlanes` true) and null object pointers in `Unlock` come back as `{"null_object": true}`. `map_info` on `DA_Item_PlayerBoxLarge` `Components` reported a `TMap` userdata with `ForEach` and `Find`, and **no** `Num`, `GetMapNum`, `Keys`, `Values` or `Length`; the MapProperty has none of `GetKeyProp`, `GetValueProp`, `GetKeyProperty`, `GetValueProperty`. So the key and value types of a map cannot be read that way, and `read` still reports maps as skipped (`key/value property not reachable`). `map_info` on a non-map returned a clean error. No crash. Next: `probe_methods` (which members exist on a property or a value, never called) and `map_peek` (types of the first map entry, no `get()`), added to learn what this UE4SS build offers; installed, **not yet run**.
- 2026-10-26 (fourth restart): `probe_methods` on the `Components` map value: `ForEach`, `Find`, `Contains`, `GetAddress` and `type` exist; `Num`, `Length`, `Keys`, `Values`, `GetMapNum`, `GetKeyType`, `GetValueType` do not. On the MapProperty: `ContainerPtrToValuePtr`, `ImportText`, `IsA`, `GetClass`, `GetFName`, `GetFullName`, `type` exist; no `GetKeyProp`/`GetValueProp`/`GetInner` variants. `map_peek` saw 2 entries (matching the 2-part recipe) whose key and value are `RemoteUnrealParam`, so their property types cannot be learned from the API; maps stay unread because a soft pointer cannot be ruled out. Reads of `CraftFilter` return only the number (no enum name). No crash.
- 2026-10-26 (fifth restart, `allow_load` on): the guards worked (a non-`/Game/` path was refused; a path that does not exist returned `loaded: false` in 0 ms; an already loaded item returned `already_loaded`). `BP_Inventory_Container_Small` and `BP_Building_Container_Small` each loaded in about 4 ms and `describe_class` could then read them. Two defects found: the tool said `loaded: false` for a Blueprint because it only looked for the asset object, not the generated class `..._C` (cooked games have only the class); and a path containing `/../` passed the character check. Both fixed (check the `_C` class too; reject `..` and `//`) and reinstalled, **not yet re-run**. No crash.

`settings.txt` carries a **risk section**: every risky option appears with its consequences in the comments right above the value, written by `bridge_settings.py init`/`set`; enabling one is just flipping its value after the user has approved.
