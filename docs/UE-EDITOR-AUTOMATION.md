# Driving the Unreal Editor from outside (MCP + Python remote execution)

Goal: author cooked assets (see [COOKED-ASSET-PIPELINE.md](COOKED-ASSET-PIPELINE.md)) without clicking through the editor, so that a widget or a Blueprint can be built, styled, compiled and saved by scripts. Everything below was verified on 2026-10-23 against our scratch project `VanillaPlusCook` (Blueprint-only, now legacy) with the launcher build UE 5.8.4 (changelist 58902052); later work (C++ base class, Slate inspector, animation binding by click, display actor) ran against the C++ project that now lives in the repository as `unreal/VanillaPlusCPP` (see PROJECT-LAYOUT.md of the game repository). The editor language was switched to English on 2026-10-24, so Blueprint node ids are English (`AddEvent|EventBeginPlay`, `UserInterface|CreateWidget`); the Portuguese ids in the older recipes below no longer match. Helper scripts live in [tools/ue-editor](../tools/ue-editor).

## Two channels, different jobs

| Channel | What it is | Strengths | Limits |
|---|---|---|---|
| **Unreal MCP** (plugin `ModelContextProtocol`, experimental) | HTTP server inside the editor, default `http://127.0.0.1:8000/mcp` | Typed tools grouped in "toolsets" (UMG, objects, assets, Blueprint graphs, sequencer, logs, config) | Experimental, loopback only, no authentication |
| **Python remote execution** (plugin `PythonScriptPlugin`) | Run arbitrary editor Python from another process | Full `unreal` API: read/set any `EditAnywhere` property, compile, save | Needs the editor open; one statement or file per call |

## Setup (one time, in the project, not in the game)

1. Enable the plugins `Unreal MCP`, `All Toolsets` (it pulls in `Toolset Registry` and every toolset plugin) and `Python Editor Script Plugin`, then restart the editor. `All Toolsets` is heavier than needed; `UMG ToolSet` + `EditorToolset` would be enough for UI work.
2. Start the MCP server from the editor console: `ModelContextProtocol.StartServer 8000` (or enable *Auto Start Server* in Editor Preferences > Model Context Protocol). Port and path come from `UModelContextProtocolSettings`; the server validates the `Origin` header and only accepts `localhost`.
3. Turn on Python remote execution. It is a project setting (`bRemoteExecution`, default `false`); it can be set through MCP itself: `ConfigSettingsToolset` > `SetSectionProperties` with container `Project`, category `Plugins`, section `Python`, then `SaveSection`. It took effect without restarting the editor (multicast `239.0.0.1:6766`, bound to `127.0.0.1`).
4. Back up the project folder (`Content`, `Config`, the `.uproject`) before letting scripts create or change assets: the project is not under version control.

## MCP protocol notes (verified)

- Streamable HTTP, protocol `2025-11-25`. `initialize` returns an `Mcp-Session-Id` header; send `notifications/initialized`, then every call carries that header.
- With *tool search* on (default) the server exposes only three tools: `list_toolsets`, `describe_toolset` and `call_tool(toolset_name, tool_name, arguments)`. Objects are passed as `{"refPath": "/Game/Folder/Asset.Asset"}`; widgets use `/Game/...Asset:WidgetTree.WidgetName`.
- **`toolset_name` is the full name.** Native toolsets look like `UMGToolSet.UMGToolSet`; Python toolsets have several dots, for example `editor_toolset.toolsets.object.ObjectTools`. A name filter that only accepts `Module.Class` hides the Python toolsets (`ObjectTools` and `AssetTools` looked missing for several steps because of this).
- `describe_toolset` returns JSON Schemas; `list_toolsets` text is long (about 14 kB) and descriptions are localized to the editor language.

## Toolsets seen on this install (names only; details through `describe_toolset`)

- **`UMGToolSet.UMGToolSet`:** `CreateWidgetBlueprint`, `AddWidget`, `MoveWidget`, `RemoveWidget`, `RenameWidget`, `ToggleWidgetAsVariable`, `GetWidgets`, `GetWidgetDescription`, `ListWidgetClasses`, `WrapWidgets`, `BindToEventProperty`, `CompileWidgetBlueprint`, UI component and named-slot helpers. No animation tools (it only reads existing animations).
- **`editor_toolset.toolsets.object.ObjectTools`:** `list_properties`, `get_properties`, `set_properties`, `reset_properties`, `get_class`, `search_subclasses`.
- **`editor_toolset.toolsets.asset.AssetTools`:** `save_assets`, `load_asset`, `find_assets`, `duplicate`, `move`, `delete`, `get_dependencies`, `get_referencers`, folder and metadata tools.
- **`editor_toolset.toolsets.blueprint.BlueprintTools`:** events, functions, variables, nodes, pins, `connect_pins`, graph text round trip (`read_graph_dsl`, `write_graph_dsl`, `get_graph_dsl_docs`), `compile_blueprint`, `create`.
- Also present: `actor`, `scene`, `material`, `material_instance`, `texture`, `static_mesh`, `skeletal_mesh`, `data_asset`, `data_table`, `curve_table`, `string_table` tools; `animation_toolset.*` (Sequencer and Control Rig); `EditorToolset.EditorAppToolset` (console variables, selection, `CaptureEditorImage`, `CaptureViewport`, Play In Editor) and `EditorToolset.LogsToolset` (read the Output Log); `ConfigSettingsToolset`; `PluginToolset`; `SlateInspectorToolset`; Niagara, PCG, GAS, physics and others we do not use.
- `AnimationAssistantToolset` is an empty skeleton in 5.8; it is not a source of UMG animation tools.

## What was verified end to end

1. MCP: `CreateWidgetBlueprint` made `/Game/Widgets/WidgetVanillaPlusMonitor`; 20 `AddWidget` calls built the intended hierarchy (`GetWidgets` confirmed it, no duplicates); `ToggleWidgetAsVariable` marked nine widgets.
2. Python remote: `unreal.load_object(None, "<asset>:WidgetTree.<name>")` loads a widget by path; `get_editor_property`/`set_editor_property` worked for `brush_color`, `padding`, `text`, `font`, `color_and_opacity`, slot `layout_data`, `size`, alignments (51 changes, 0 failures); `BlueprintEditorLibrary.compile_blueprint` and `EditorAssetLibrary.save_asset` worked. The styled monitor asset was cooked and converted with `retoc` (verified container); it has not been loaded in the game yet. The earlier minimal test widget did load in the game ([COOKED-ASSET-PIPELINE.md](COOKED-ASSET-PIPELINE.md)).
3. Blueprint logic through MCP (user-verified in Play In Editor, 2026-10-23): `UMGToolSet.BindToEventProperty` created the `OnClicked` events of `BtnPage1..3`; `BlueprintTools` `find_nodes`, `get_node_infos`, `create_node`, `connect_pins`, `set_pin_value` built `OnClicked -> Display.SetActiveWidgetIndex(N-1)` for each button; `AssetTools.save_assets` / `is_dirty` saved it. The tabs switch the page panel when clicked. Script: `tools/ue-editor/examples/wire_tabs.py` (uses `tools/ue-editor/mcp_client.py`).
4. Reading the editor log and the engine source were never needed for the above, but both are available (`LogsToolset`; `<engine root>\Engine\Source`, indexed in GitNexus as `ue58-source`).

## UMG facts that cost us time (source-backed)

- `UOverlaySlot` defaults to `HAlign_Left` / `VAlign_Top` (`Runtime/UMG/Private/Components/OverlaySlot.cpp`): a child of an Overlay is not filled unless its slot alignment is set to Fill.
- A `Border`'s background brush property is `background` (not `brush`); its tint is `brush_color`. Rounded corners use `draw_as = ROUNDED_BOX` plus `outline_settings.corner_radii`.
- `FSlateChildSize(value, SlateSizeRule.FILL)` sets proportional sizing in horizontal/vertical box slots.
- A widget placed in a `CanvasPanel` slot needs `layout_data` (`AnchorData`: offsets = position and size, anchors, alignment) to be centered.

- **Button content is centered and padded** (verified in game, 2026-10-24): the content slot of a `Button` defaults to centered both ways, and the button style adds `normal_padding` / `pressed_padding` of (12, 1.5, 12, 1.5). A highlight inside a button therefore shrinks to its content and is inset from the sides until both are fixed (slot alignment fill, style paddings zero).
- **`SizeBox` overrides need the setters**: `set_editor_property('width_override')` only stores the value; call `set_width_override()` / `set_height_override()` or the SizeBox ignores it. A SizeBox around a widget with its own size (an `Image`) exposes the bug.
- **The widget designer shows `Hidden` widgets**, so a capture of the designer cannot confirm hide/show logic. Judge visibility in Play In Editor (a screenshot of the editor with PIE running works through `CaptureEditorImage`; temporarily set the monitor's `Opening` default to true in memory, never saved).
- **Translucent fills look much stronger in the 3D widget** than the same alpha in the Penpot: 0.07 to 0.10 amber looked like an opaque bar in game, 0.02 to 0.03 matches the design. The whole UI also renders lighter than the hex colors of the design (the dark blues come out blue-gray).
- Widgets cannot always be deleted while the editor holds references (`delete_asset` returned false and warned about a corrupt package). Rebuild in place instead (`build_terminal_os.py --rebuild` empties the asset first).

## Blueprint graph gotchas (verified)

- Node type ids are **localized** to the editor language (this editor reports Portuguese: `Gerenciador|SetActiveWidgetIndex`, `Variáveis|<Blueprint>|Obter<Variable>`). Look them up with `find_node_types` (use `type_id_filter`) on the actual install; do not hard-code English ids.
- `add_component_bound_event` only accepts actor components. For widget events (`OnClicked`, `OnHovered`, ...) use `UMGToolSet.BindToEventProperty(widgetBlueprint, eventName, propertyName, propertyClass)`; the widget must already be marked as a variable.
- `read_graph_dsl` returns an empty string for graphs whose only nodes are widget-bound events; the node-level API (`find_nodes`, `get_node_infos`, `create_node`, `connect_pins`, `set_pin_value`) works there.
- `get_node_type_pins` returns pin names and a throwaway node reference; it did not leave a node in the graph.
- `compile_blueprint` returns no value (`None`) even on success; confirm in the editor or by behavior.

## Not verified yet

- `ObjectTools.set_properties` over MCP (the monitor styling used editor Python instead).
- Whether the Sequencer tools or Python can create a `WidgetAnimation` (the UMG animation asset); the MCP UMG toolset has no animation tool.
- `CaptureEditorImage`/`CaptureViewport` as a visual feedback loop.
- Using the editor itself as the preview (Play In Editor) instead of restarting the game for each asset change; PIE was used by the user to check the tabs, but not as an automated loop.
- Blueprint logic of a cooked asset of ours running **inside the game** (the tab wiring was only tested in PIE; the monitor container is not mounted in the game yet).

## Safety

- Loopback only and without authentication: any local process can drive the editor while the server runs. Stop it (`ModelContextProtocol.StopServer`) when not in use.
- The plugins are experimental and editor-only; none of this is shipped to the game. Do not commit the project, the cooked output or any converted container.
- `retoc manifest` writes `pakstore.json` into the current directory (8.7 MB for the game container): run it outside the repository.

## Scripts

| File | Use |
|---|---|
| `tools/ue-editor/ue_remote.py` | Run a statement or a script file in the open editor (`--file`) |
| `tools/ue-editor/mcp_call.sh` | Minimal MCP client: `init`, `list`, `describe <toolset>`, `call '<json>'` |
| `tools/ue-editor/mcp_client.py` | Python MCP client (`Mcp().call(toolset, tool, args)`) for scripts that chain calls |
| `tools/ue-editor/umg_add.sh` / `umg_tree.py` | Add one widget; print the tree returned by `GetWidgets` |
| `tools/ue-editor/examples/` | `monitor_style.py` (editor Python styling), `compile_and_save.py`, `wire_tabs.py` (Blueprint wiring over MCP) |

## Live Coding with the editor open (2026-10-27)

`LiveCoding.Compile` (console command, sent through `ue_remote.py`) compiled a new `UBlueprintFunctionLibrary` class of the editor plugin while the editor stayed open: the log shows "Live coding succeeded" after about a minute. The class was then callable from Python via `unreal.get_default_object(unreal.load_class(None, '/Script/<Module>.<Class>')).call_method('<FunctionName>', args=(...))`, but `hasattr(unreal, '<Class>')` stayed false until a restart. Verified for a function library only; using a Live-Coded native class as a Blueprint parent was a problem earlier. The editor log notes that data type changes after Live Coding may break packaging.
