# Bridge capabilities: what UE4SS offers, what the bridge exposes, what we actually need

Sources: the UE4SS Lua API summary at docs.ue4ss.com (marked there as version 3.0.0 and possibly out of date), and a count of the API calls our hand-written probes used in `mods/` (2026-10-26). "Need" is how often a probe had to do it by hand.

## Coverage

| UE4SS capability | Bridge today | Need (probe uses) | Risk | Plan |
|---|---|---|---|---|
| `FindAllOf`, `FindFirstOf` | `find_all` | 46 / 3 | low | done |
| `StaticFindObject`, object paths | `get` / `describe_class` (by path) | 49 | low | done; add a plain `find_object` |
| `GetFullName`, `GetFName`, `GetClass`, `IsValid`, `GetOuter`, `GetOwner` | used inside ops | 84 / 77 / 39 / 12 / 2 / 6 | low | done |
| `ForEachProperty`, `ForEachFunction`, `GetSuperStruct` | **`describe_class`** (verified once on 2026-10-26, incl. a missing class) | 16 / 12 / 11 | medium (a past crash was here) | done, one run |
| Property reads (`__index`) | `get` (soft pointers skipped) | many | medium | done |
| `TArray` (`GetArrayNum`, `ForEach`, index) | **`get_array`** (verified once on 2026-10-26, incl. a non-array property) | 3 | medium | done, one run |
| Struct members (`UScriptStruct`, `StructProperty:GetStruct`) | **`read`** (verified once, 2026-10-26: `Unlock`, nested `ViewTarget`) | needed for `ViewTarget`, the asset-manager settings | high before the test, none seen | done, one run; maps/sets still skipped |
| `GetCDO`, `IsChildOf`, `IsA` | **`cdo:` object references** (verified once) | CDO values (class defaults) | low | done; `IsChildOf`/`IsA` not exposed |
| `UEnum` (`GetNameByValue`, `ForEachName`) | enum name inside `read` (worked for `EVoyageSkillUnlockMethod`) | enum names for property values | low | done for values; `ForEachName` (list all names) not exposed |
| `ForEachUObject` | none | 2 (registry scans) | medium: touches every object | **`scan`** (verified once: 226k objects, about 1 s) |
| Property writes, `CallFunction`, `UFunction:__call` | **none on purpose** | F9 capacity probe (`SetMaxWeightOverride`) | high | later, behind an `allow_writes` setting that defaults to off, with the journal |
| `RegisterHook` / `NotifyOnNewObject` / `RegisterBeginPlayPostHook` | none | 6 / 1 | high (a hook on every actor is a past crash suspect) | later, observe-only, one hook at a time |
| `LoadAsset` | **`load_asset`** (written 2026-10-26, off by default, asks the user first) | 11 | high | written; test with one small asset; own cooked assets need the AssetRegistry technique, not covered |
| `StaticConstructObject` | none | 3 | high | later |
| `ProcessConsoleExec`, console command handlers | none | the F10 console is used by hand | medium | later |
| `ExecuteInGameThread`, `LoopAsync`, `ExecuteWithDelay` | used by the bridge | 58 / 15 | low | done |
| `UE4SS:GetVersion`, `UnrealVersion` | none | engine/UE4SS version is read from the log by hand | low | add to `ping` |
| `Mod:SetSharedVariable` / `GetSharedVariable` | none | none yet | low | skip |
| `TMap`, `TSet` | not listed in the docs summary | unknown | unknown | check against the installed UE4SS before relying on it |

## Rules that stay
- Read first; every new op is run once on its own before the next one is added. The crash on 2026-10-26 came from a path (missing property) that the first successful reads never exercised, so each op's failure paths are tested too.
- Writes, calls, hooks and asset loading are off by default and need an explicit setting plus journal entries.
- Never keep a `UObject` between requests.

## Not covered by UE4SS itself (our part)
Editor integration, cooking and deployment (`tools/deploy`), build drift (`tools/drift`), evidence notes, per-game profiles. See `docs/GAME-PROFILES.md`.
