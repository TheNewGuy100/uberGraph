# Per-game profiles and the tool/game split (design draft, 2026-10-26)

Status: **step 1 implemented (2026-10-26), the rest is proposal.** Done: `profiles/the-last-caretaker.example.json` (tracked), `profiles/*.local.json` (ignored, holds the real paths), the loader `tools/profile/game_profile.py`, and `tools/ue-editor/ue_remote.py` reads `engine.root` from it (order: `UE_ENGINE_ROOT`, profile, old default). Checked: with the editor closed the script reaches the editor search, meaning the engine path from the profile resolves; a wrong `UE_ENGINE_ROOT` fails as expected. Not checked against a running editor. Goal: separate what is a reusable tool from what describes one game, so the same workflow can later serve other Unreal games, and say honestly which games and versions each part is known to work with. Name and scope of a future standalone project are left open on purpose.

## Three layers

| Layer | What it holds | Today |
|---|---|---|
| **Tools (reusable)** | editor automation (MCP and Python remote), cook and convert, deploy with backup, in-game probes, crash triage, repository hygiene, evidence notes | `tools/ue-editor`, `tools/cue4parse-mcp`, `tools/lua-check`, `tools/check-repo-hygiene.sh`, the cook steps in `docs/COOKED-ASSET-PIPELINE.md` |
| **Game profile (data)** | everything that identifies one game and one build | partly in `tools/cue4parse-mcp/games.local.json` (id, name, installRoot, archivesPath, engineVersion, mappingsPath); the rest is spread over docs and commands |
| **Mod project** | the mod itself: Lua, assets, scripts that build them | `mods/`, an authoring project (see `unreal/example`), `analysis/` for this game |

The profile is what the tools read instead of hard-coded paths such as `F:\Steam\...` or `UE5_8`.

## Profile fields, taken from what this project has actually needed

| Field | Example (The Last Caretaker) | Used by |
|---|---|---|
| `id`, `name` | `the-last-caretaker` | everything |
| `steamAppId`, `buildId` | `1783560`, `25982825` | drift check |
| `engine.version`, `engine.editorBuild` | `5.8`, `5.8.4 (CL 58902052)` | cook, retoc, editor project |
| `exe.path`, `exe.sha256` | `VoyageSteam-Win64-Shipping.exe`, hash | drift check, crash triage |
| `containers` | `Content/Paks`, IoStore (`.utoc/.ucas`) | extraction, deploy |
| `mappings.path`, `mappings.sha256` | `.usmap` for this build | asset parsing |
| `ue4ss.path`, `ue4ss.version` | `ue4ss/`, v3.0.1 beta | probes, deploy |
| `launch.options` | `-noraytracing`; `-dx11` only when FSR is on | run |
| `deploy.allowed` | our `z*_P` containers and `ue4ss/Mods/<our mods>` | deploy (never original game files) |
| `deploy.backupDir` | `F:\Backups` | deploy |
| `knownIssues` | FSR FG crashes DX12 on RTX 3060 | notes |

Rule that stays from `AGENTS.md`: the profile never contains the game's content, keys or mappings, only paths and hashes. Local values live in an ignored `*.local.json`, an example without private values is committed.

## Support matrix (what we can say today)

Legend: **verified** = used successfully in this project; **claimed** = stated by the tool's own docs or sources, not exercised here; **unknown**.

| Part | Engine versions | Evidence |
|---|---|---|
| Editor Python remote execution | UE 5.8 verified; older versions unknown | used on the 5.8.4 launcher build |
| Editor MCP plugin (`ModelContextProtocol`, toolsets) | UE 5.8 verified; availability in other versions unknown | experimental plugin on 5.8.4 |
| `retoc to-zen` (legacy cooked assets to IoStore) | UE 5.8 verified; claimed UE4_25, 4_26, 4_27, 5_0 through 5_8 | `retoc 0.1.5 to-zen --version` lists these values |
| CUE4Parse (reading containers) | UE 5.8 verified with the supplied mapping; version list comes from the pinned package `1.2.2.202610` (`EGame` values) | `tools/cue4parse-mcp` |
| UE4SS | UE 5.8 verified (`Found EngineVersion: 5.8`, v3.0.1 beta); claimed 4.12 to 5.7 by its releases page and README copies | per-game success is not guaranteed even for listed versions |
| Cooked asset loaded from Lua (AssetRegistry trick) | one game, one engine | `BP_ProbeActor`, widget tests |
| GitNexus indexing, hygiene script | engine independent | n/a |

Not yet tested at all: any second game, UE4 titles, games with encrypted or signed paks, custom-engine builds, games with anti-cheat.

## What kind of project this would help (honest scope)

- **Fits:** single-player or offline UE games where UE4SS runs, where a cook from the matching launcher engine version is accepted, and where extra containers can be mounted.
- **Probably does not fit:** online games with anti-cheat, encrypted or signed paks, engines with custom serialization. The `AGENTS.md` guardrails already rule out bypassing those.
- **Version coupling to remember:** the cook only worked because our editor version matches the game's engine. A game on another engine version needs the same editor version (or at least a compatible one), which is a profile field, not a global setting.

## Proposed next steps (in order)

1. **Done:** the example profile, the loader and `ue_remote.py` reading `engine.root` (verified against the open 5.8.4 editor).
2. Move the deploy-with-backup-and-hash step out of ad hoc commands into one script that reads the profile and refuses paths outside `deploy.allowed`.
3. **Done (2026-10-26):** `tools/drift/check_drift.py` compares, read-only, the Steam build id, the exe SHA-256, the sizes of the original containers (sizes, because one is 16 GB; our `z*_P` files are ignored) and the mapping SHA-256 with the profile. A baseline missing from the profile is reported as NO BASELINE, never as a pass; `--record` fills only missing baselines in a `.local.json` profile. Exit code 0 no drift, 1 drift, 2 nothing comparable. `deploy.py copy ... --check-drift` aborts when it finds drift. Against the installed game today: build 25982825, exe `08228B72…`, 8 containers and the mapping all match (no drift). 9 unit tests pass (`python tools/drift/test_drift.py`). Function fingerprints are not part of this yet.
4. Only after 1 to 3 work for this game, try a second game to learn what is really game specific. Until then, do not claim support for other games.

Tool added with route 2: `tools/usmap/usmap_tool.py` (reads the profile's `mappings.path`; read-only). It works only on uncompressed usmaps and refuses anything it cannot parse exactly.
