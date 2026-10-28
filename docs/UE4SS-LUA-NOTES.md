# UE4SS Lua notes (verified on this game)

What works and what fails when scripting The Last Caretaker with UE4SS Lua. Target: UE 5.8, UE4SS v3.0.1 beta (`83330635`). Static analysis was done on Steam build `25191271`; the runtime observations here (2026-10-22) ran on the updated build `25982825` (game version string `0.10.0.653173` on screen). Every item cites the evidence it rests on. **Observed** means seen in a user-provided log or screenshot. **Inferred** means reasoned from observations. Do not treat anything here as general UE4SS behavior: it may differ in other builds or UE4SS versions.

No Lua interpreter exists on this machine, so the UE4SS runtime is the only syntax and API check. A `pcall` that swallows an error hides missing arguments, so always log the error text.

## Calling conventions (observed)

| Topic | Rule | Evidence |
|---|---|---|
| Structs | Pass structs as Lua tables: `{R=, G=, B=, A=}`, `{X=, Y=}`. `FLinearColor(...)` and `FVector2D(...)` are not callable globals. | 2026-10-18 menu run stopped at `FLinearColor(...)`; table form worked afterwards. |
| Enums | Enum globals such as `ESlateVisibility` were `nil`. Use the underlying numbers: Visible `0`, Collapsed `1`, `EMouseLockMode::DoNotLock` `0`. | 2026-10-18 run: `ESlateVisibility` nil at the first `SetVisibility`. Numbers worked. |
| Out parameters | Pass empty Lua tables and read them by parameter name. `GetMousePositionScaledByDPI(pc, mouseX, mouseY)` fills `mouseX.LocationX` and `mouseY.LocationY` and returns a bool. | Same run: the call needed two Out tables, and clicks hit-tested correctly afterwards. |
| Missing arguments | `SetInputMode_GameOnly(playerController, true)` needs the `bFlushInput` argument. Without it the call failed, and `pcall` hid the failure. | 2026-10-18 log review. |
| Object paths | `LoadAsset` needs the full `Package.Object` path (for example `/Game/Data/.../DA_Item_X.DA_Item_X`). | 2026-10-18 Recipimaxi1000 log. |
| Threading | UMG and object changes ran inside `ExecuteInGameThread`. Key callbacks only dispatch to it. | Menu and clone code. This is a convention that worked, not a proven requirement. |

## UMG widgets (observed)

- Create the widget with `WidgetBlueprintLibrary:Create(world, UserWidgetClass, playerController)`. Build children with `StaticConstructObject(class, menuWidget.WidgetTree, FName(...))`, assign `WidgetTree.RootWidget` to a `CanvasPanel`, then use `canvas:AddChildToCanvas(widget)` and the slot's `SetPosition`/`SetSize` with tables. Use unique `FName`s. Evidence: the F2 menu works.
- Confirmed in game: `AddToViewport`, `SetVisibility` with numbers, `Border:SetBrushColor`, `Button:SetBackgroundColor` (multiplies the default gray, so dark colors with alpha give dark translucent buttons), `TextBlock:SetText(FText(...))`, also for later text updates. Evidence: the user's screenshots on 2026-10-22.
- `TextBlock:SetColorAndOpacity({SpecifiedColor = color, ColorUseRule = 0})` and `label.Font.Size = n` raised no error and the text visibly changed color and size. Evidence: the 2026-10-22 log has no `nao suportado` warning, and the screenshots show it. Sizes 16 to 22 were tried, and 22 overflowed a 168 px column ("VANILLAPLUS" took about 187 px).
- Hit-testing is manual. `GetMousePositionScaledByDPI` coordinates matched absolute `CanvasPanel` positions at roughly 1920x1080. Inferred: other resolutions or DPI settings are untested.
- Input mode: open with `SetInputMode_GameAndUIEx(pc, widget, 0, false, true)` and `bShowMouseCursor = true`. Close with `SetInputMode_GameOnly(pc, true)` and restore the previous cursor state. Evidence: user-confirmed open, close and camera restore.

## Data and arrays (observed)

- `VoyageSkill.Items` reads as a `TArray`, with `count` and `capacity` loggable. The Lua `TArray` wrapper has no `Add`: `items:Add(x)` raises `TArray index out of range`. **Do not retry it.** Evidence: Recipimaxi1000 log, 2026-10-18.
- `StaticConstructObject` can create a distinct in-memory clone of a `VoyageItem`, and `Name`/`Description` assignments return success. The clone is not registered anywhere, so it is not buildable. Evidence: same log.
- Reflected `Unlock` structs read fine (`UnlockMethod`, `Cost`, `Requirement`): Torch `(2, 0, 1)`, FortiHold `(2, 1, 11)`. Their meaning is inference only. See [HYPOTHESES.md](../analysis/HYPOTHESES.md), H6 and H7.
- `ForEachFunction` hit `attempt to call a nil value` in its callback on the first class chain. Restricting enumeration to `/Script/Voyage` classes and returning nothing from the callback worked. Evidence: 2026-10-18 changelog entry.

## Hooks, keys and time (observed)

- `RegisterKeyBind(Key.F2, fn)` and `RegisterKeyBind(Key.LEFT_MOUSE_BUTTON, fn)` work. One key per mod: disable the other mod's `mods.txt` entry to avoid a collision (see [mods/README.md](../mods/README.md)).
- `/Script/Engine.Actor:ReceiveBeginPlay` registers as a hook (hook IDs 142/142). Behavior inside actors is untested.
- `UEHelpers.GetGameplayStatics():SetGlobalTimeDilation(world, scale)` is logged as applied (`Time dilation: ...`) for 0.25x and 1.0x in the 2026-10-22 session. The user observed 0.5x and 2.0x earlier (older menu and SlowMo mod), but not 4.0x so far. The effect is never measured with frame timing.

## Fade and timers (observed)

- `menuWidget:SetRenderOpacity(v)` is accepted on a `UserWidget` and the user confirmed a visible fade in and out. `ExecuteWithDelay(ms, fn)` chained with `ExecuteInGameThread(step)` ran without errors or warnings through 8 opens and closes in a row, including quick toggles. Evidence: `UE4SS.log`, 2026-10-22 21:34, plus the user's report (not recorded on video).
- Real timing: a nominal 10 x 20 ms fade took 248 to 354 ms by log timestamps (about 25 to 35 ms per step). Do not rely on `ms` being exact; derive progress from step counts or a clock, and treat the delay as a minimum.
- Pattern that worked: a token incremented per fade, so an older chain stops when a newer one starts, and the close actions run only after the fade-out finishes.
- The `LoopAsync` and the 4.x `LoopInGameThreadWithDelay` alternatives were not tried.

## Escape and files (observed 2026-10-22)

- `RegisterKeyBind(Key.ESCAPE, fn)` registers and fires, both with the mod menu closed (`menuOpen=false`) and open (`menuOpen=true`, three presses logged at 21:41:45, 21:41:46 and 21:42:18). UE4SS therefore sees Escape in both states. The log cannot say what the game did with the same key. The user reported that the game was paused: with the mod menu open (`GameAndUI` input mode) the game's pause also reacted to Escape, so the mod and the game both handle the key. The user's message did not say which presses paused it, so this is read as the menu-open case. Escape was also received right after the menu closed (21:42:27), so the close and the input restore did not break key delivery.
- `io`, `os.remove` and `debug.getinfo` exist in the mod's Lua state. `debug.getinfo(1,"S").source` returns `@<game>\...\Mods\<ModName>\Scripts\main.lua`, which gives the script directory. Writing, reading back and deleting `vp_probe.txt` worked in the script directory and in the current directory (`write=true readback=true removed=true` in both). The current directory's real path was not logged, so use the script directory for anything persistent.
- Keybind persistence is therefore technically possible with a plain text file in the mod folder. Writing under the Steam `Mods` folder is still outside the repository; keep configs out of Git.

## Input mode and Escape (observed 2026-10-22)

- `library:SetInputMode_UIOnlyEx(playerController, widget, 0, true)` is accepted (log: `input mode aplicado: UIOnly`, no fallback). With the mod menu open in this mode, the user reports that the game's Escape did not interfere (no pause menu), while the mod still received Escape through `RegisterKeyBind` (eight presses logged at 21:44:46 to 21:44:47) and the menu could be closed afterwards. After the menu closed, Escape was still delivered to the mod and the game's own handling is expected to resume (not separately reported). Source for the interference claim: the user's statement plus the log; there is no frame-level proof.
- With `GameAndUI` the same Escape also paused the game (user report). So input mode is the layer that decides who owns Escape; the Enhanced Input mapping-context route was not needed.
- Cost: character and camera are frozen while the menu is open in `UIOnly`. The world keeps running unless time dilation is changed.

## Widgets created by the game (observed 2026-10-23)

- `NotifyOnNewObject("/Game/UI/Menu/BP_VoyageInGameMenu.BP_VoyageInGameMenu_C", fn)` fired exactly once per creation of the pause widget (four pause openings logged, no duplicates). `LoadAsset("/Game/UI/Menu/BP_VoyageInGameMenu.BP_VoyageInGameMenu")` loaded the widget Blueprint (`ok=true`) when `StaticFindObject` had not found the class yet; registration 5 s after the mod loaded still caught later creations.
- Reading the new object about 1 s later on the game thread worked: `GetFullName`, `IsInViewport`, `GetVisibility` (a number), `GetGameplayStatics():IsGamePaused(world)`, the property `menu.NavigationContainerRootPanel`, `box:GetChildrenCount()`, `box:GetChildAt(i)`, `child:GetFName():ToString()`, `child.Text:ToString()` (localized string) and `child.Slot.Padding` (fields `Left/Top/Right/Bottom`). `menu:GetWidgetFromName(FName("..."))` did not give a valid widget (the reason was not logged), while the property read did.
- `UClass:ForEachProperty(function(prop) ... end)` worked with no return value; it lists only the properties declared on that class, not the ones inherited from its parents. `prop:GetFName():ToString()` and `prop:GetClass():GetFName():ToString()` gave the name and the property type.
- `UClass:ForEachFunction(function(fn) ... end)` also worked (no return value): 21 functions were listed for `/Script/Voyage.VoyageFocusableWidget`. Note that `Restart All Mods` in the UE4SS console reloaded the mod at runtime (`Stopping mod ... for uninstall`, `All mods re-installed`) and `[FCallbackGarbageCollector] Freed invalid callbacks!` followed; duplicate callbacks after a reload were not tested.
- `object:GetClass()` and `class:GetSuperStruct()` walk the class chain; `class:GetFullName()` gives the type prefix and path (for example `Class /Script/Voyage.VoyageFocusableVerticalBox`).

## Operations

- Mods reloaded at runtime on 2026-10-22 (log: `Stopping mod ... for uninstall`, `Starting Lua mod`, at 21:22:17 and 21:25:53) while `EnableHotReloadSystem = 0` and `EnableAutoReloadingLuaMods = 0` in `UE4SS-settings.ini`. **How the reload was triggered was not recorded**; the GUI console (`Ctrl+O`) is a candidate. Treat "restart the game after each edit" as the safe default until this is confirmed.
- `Keybinds` (UE4SS built-in): `Ctrl+J` object dump, `Ctrl+H` C++ headers, `Ctrl+Num9` UHT headers, `Ctrl+Num8` static meshes, `Ctrl+Num7` all actors, `Ctrl+Num6` `.usmap`, `Ctrl+Num5` `.jmap`. None of the dumps was run in this project yet. Dumps contain game-derived content and must stay outside the repository. Three UE4SS crash dumps from 2026-10-17 exist in `ue4ss/`; their cause is unknown, so back up before the first heavy dump.
- Back up `mods.txt` and the script before every change and note the backup path in the changelog.

## Open questions

- Does `TArray` mutation work through any supported path, or only through game UFunctions?
- What triggers the observed runtime mod reload?
- Does the pause menu stay closed over a longer session with `UIOnly`? Escape is planned as the reserved cancel key of the keybind capture screen; its exact behavior there is untested.
- Can Lua state be shared between mods? Mods are believed to run in separate Lua states (not verified here), so the global `VanillaPlusMenu.addPage` is untested across mods.
- Do the UE4SS dumps run safely on this build?

- `GameplayStatics:PlaySound2D` must receive all 8 parameters (`world, sound, volume, pitch, startTime, nil, nil, true`); with 5 it throws `UFunction expected 8 parameters, received 5`. Game cues load with `LoadAsset("/Game/Audio/SFX/UI/UI_Gen/CUE_UI_Gen_Popup_Open.CUE_UI_Gen_Popup_Open")` and play (verified).
- `widget:SetRenderTranslation({X = ..., Y = ...})` works and, combined with `SetRenderOpacity`, gives a slide-in/out (verified).

- **Crash:** passing a Lua table for a `TSoftClassPtr` parameter (`KismetSystemLibrary:LoadClassAsset_Blocking({AssetPathName=..., SubPathString=""})`) crashed the game with `EXCEPTION_ACCESS_VIOLATION reading address 0x70` (null dereference), not a Lua error. Do not pass soft pointers as tables. `StaticLoadObject`, `LoadObject`, `StaticLoadClass` and `LoadClass` are `nil` in UE4SS 3.0.1 here; `LoadExport` exists (semantics not verified).

- **`LoadAsset` is asset-registry gated** (read from RE-UE4SS `Mod/LuaMod.cpp`): it calls `UAssetRegistryHelpers::GetAssetRegistry()->GetAssetByObjectPath(name)` and only if that returns a valid `FAssetData` it calls `UAssetRegistryHelpers::GetAsset`; when nothing is found it prints nothing (no `Asset loaded` line) and still returns normally. It returns three values: the object, `was_asset_found`, `did_asset_load`. It must run on the game thread. A package in our own mounted container (not in the game's registry) is therefore never loaded by it, although the container is mounted (handles open on the `.utoc`/`.ucas`).
