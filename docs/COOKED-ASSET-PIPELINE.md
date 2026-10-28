# Cooked asset pipeline (verified end to end, 2026-10-23)

Goal: author a Widget Blueprint in our own Unreal project, cook it, convert it to an IoStore container the game mounts, and show it from the UE4SS Lua mod. Verified in game with a minimal widget (`CanvasPanel > ScaleBox > TextBlock`). Game build 25982825 (version 0.10.0.653173), engine 5.8.4 (changelist 58902052, launcher build) installed at `F:\Engines\UE_5.8`.

## Layout (nothing below is committed; proprietary or generated)

| What | Where |
| --- | --- |
| Authoring project (C++ project, trimmed; see PROJECT-LAYOUT.md of the game repository) | `unreal\example` in this repository is the example (only `.uproject`, `Config`, `Source` and the plugin source are tracked); copy and rename it for your game |
| Cook output (ignored by git) | `<project>\Saved\Cooked\Windows` |
| Legacy authoring project (Blueprint-only), kept as a fallback | `F:\Projetos\VanillaPlusCook` (outside the repository) |
| Converted container and logs | `F:\Apps\VanillaPlus-Cook\out`, `cook-N.log` |
| retoc | `F:\Apps\VanillaPlus-Tools\retoc-v0.1.5-rc3\extracted\retoc.exe` |

## Steps

1. **Author** the asset in the editor under `/Game/...` using engine classes only (the first test used `/Game/Widgets/WidgetVanillaPlusMenu`).
2. **Cook** one package, loose files, no Zen store:

   ```powershell
   UnrealEditor-Cmd.exe <project>\<Project>.uproject -run=Cook -TargetPlatform=Windows `
     -PACKAGE=/Game/Widgets/WidgetVanillaPlusMenu -SkipZenStore -unattended -nosplash -stdout
   ```

   Facts from the engine source (`CookCommandlet.cpp`) and the logs: `-PACKAGE=` selects packages (`-CookSinglePackage` does nothing here); without `-SkipZenStore` the output goes to the editor's Zen store and no `.uasset` files are written; the cook also writes the engine base content (about 586 packages), which is ignored in the next step; a full cook deletes the previous output (incremental cooking is off by default).
3. **Convert** to IoStore with the filter on the asset name:

   ```powershell
   retoc.exe to-zen --version UE5_8 --filter WidgetVanillaPlusMenu <Saved\Cooked\Windows> <out>\zVanillaPlusMenu_P.utoc
   ```

   `retoc verify` prints `verified`; `retoc info` matches the game container on TOC version, container header version and mount point (`../../../`); ours is uncompressed. Do not run `retoc manifest` inside the repository: it writes `pakstore.json` (8.7 MB for the game container) into the current directory.
4. **Mount**: copy `.utoc`, `.ucas` and `.pak` (new files only) into `Voyage\Content\Paks`. The game opens the `.utoc` and `.ucas` at startup (file handles seen open), so a game restart is needed after adding a container. To revert, delete the three files.
5. **Load from Lua** (see `docs/UE4SS-LUA-NOTES.md`): UE4SS `LoadAsset` is asset-registry gated and silently ignores packages from our container. Workaround that works: `AssetRegistryHelpers:CreateAssetData(<loaded known asset>)`, rewrite `PackageName`, `PackagePath`, `AssetName` (the `_C` class name), then `AssetRegistryHelpers:GetAsset(data)`; afterwards `StaticFindObject` finds the class, `WidgetBlueprintLibrary:Create(world, class, playerController)` builds the widget and `AddToViewport` shows it. In the mod this is the F10 action (`toggleCookedWidget` in `mods/VanillaPlusMenuPrototype/Scripts/main.lua`).

## Update 2026-10-24: authoring from `VanillaPlusCPP`, and Blueprint actors

- The authoring project was first created at `<Documents>\Unreal Projects\VanillaPlusCPP` (C++ template) and on 2026-10-24 moved into the repository as `unreal\VanillaPlusCPP`, stripped of the template code, content and config (see PROJECT-LAYOUT.md of the game repository); `VanillaPlusCook` is legacy. The cook works from it as long as the cooked packages reference only engine, UMG and game classes (check the cooked `.uasset` for `/Script/VanillaPlusCPP`; a package that references it cannot load in the game).
- **Run the cook from PowerShell, not Git Bash.** Git Bash rewrote `-PACKAGE=/Game/VanillaPlus/BP_ProbeActor` into `C:/Program Files/Git/Game/VanillaPlus/BP_ProbeActor`; the cook then warned `Unable to find package for path`, cooked every package of the project instead and produced no output for ours.
- The cook returned `exit=1` in both runs, with an `LoadErrors` line about `GameFeatureData` from the template; the cooked files were written anyway. The cause of the exit code was not investigated.
- The cook ran while the editor of the same project was open; commit charge was 32 of 39 GB. Close the editor if memory is tight (error 1455 happened once without that margin).
- A Blueprint `Actor` of ours (`/Game/VanillaPlus/BP_ProbeActor`) loads through the same `FAssetData` rewrite, spawns with `world:SpawnActor` and attaches with `K2_AttachToActor` in the game; see [CAMERA-MANAGER-PROBE.md](../analysis/CAMERA-MANAGER-PROBE.md#cooked-actor-test-user-ran-it-in-a-match-2026-10-24-033111).

## Not verified yet

- Whether the same data works for materials, textures and meshes, or for blueprint logic beyond engine nodes.
- Whether `retoc` output survives a future game build (re-check the container header version with `retoc info` after each update).
- A clean way to add our package to the game's asset registry instead of the `FAssetData` rewrite.
- Hooks (`RegisterHook`) on functions of a cooked blueprint of ours, and `PlayAnimation` from Lua.
- The difference between the editor's engine build (5.8.4) and the game's exact engine build (the executable only reports `UE5-CL-0`).

## One-command flow and the first user meshes in the game (2026-10-27)

`tools/cook/cook_and_pack.py` runs steps 2 to 4 above in one command (cook without a shell, `retoc to-zen`, `retoc verify`, a scan for forbidden references to `/Script/VanillaPlusCPP` and `/Script/VanillaPlusEditorTools`, then with `--deploy` the copy into the game's Paks through `tools/deploy` with the drift check). Its settings come from the game profile (`cook.retoc`, `cook.outDir`, `engine.retocVersion`). Example: `python tools/cook/cook_and_pack.py --container zVanillaPlusChest_P --package /Game/VanillaPlus/BP_RecipimaxXL --filter RecipimaxXL`. Run it from PowerShell (the package path starts with a slash).

First use: `BP_RecipimaxXL` (an `Actor` with two static mesh components, the author's `SM_RecipimaxXL_Body` and `SM_RecipimaxXL_Lid` at scale 0.02, roll -90, lid at (0, -80, 140)). The container (3 packages, 126,793 bytes in the `.ucas`) verified, was deployed (`zVanillaPlusChest_P`) and, after a game restart, `VanillaPlusChestProbe` (Num7) spawned it in front of the player. **User-verified:** the meshes loaded and the actor spawned with collision active, seen as a dark untextured box (no material was authored; the grid material does not show, so the game shows its default). The actor appeared turned sideways to the player; orientation is not a concern yet because the container is meant to be placed from the build menu.

Not tested: textures or materials, the lid opening, any game-class component, saving and loading with the actor placed.
