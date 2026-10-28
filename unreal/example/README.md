# Example authoring project

A minimal Unreal C++ project that uberGraph's editor tools expect, to copy and rename for your own game:

- `ExampleProject.uproject`: an empty game module (so the project builds as a C++ project) and the editor plugins the tools use.
  `EngineAssociation` is `5.8`; set it to the engine version of your game.
- `Plugins/UbergraphEditorTools`: an editor-only plugin. `UUbergraphLayoutLibrary::DumpStructLayout` dumps the reflected layout of a class or
  struct as JSON, so a generated stand-in can be checked against the real one (`tools/ue-editor/examples/dump_layouts.py`,
  `tools/usmap/compare_layout.py`). It is never cooked into a mod.
- `Config/`: the minimum, including `bRemoteExecution=True` so `tools/ue-editor/ue_remote.py` can drive the editor from outside.

Not included (and git-ignored): `Content/`, `Intermediate/`, `Binaries/`, `Saved/`, and the generated stand-in plugin for your game
(`tools/usmap/gen_stubs.py --out <project>/Plugins/<GameName>Stubs <classes>`). If you add a stand-in plugin, enable it in the `.uproject` as
an optional plugin.

Rule that stays: **nothing the game loads may reference `/Script/ExampleProject` or `/Script/UbergraphEditorTools`**, because the game does not
have them. `tools/cook/cook_and_pack.py` scans the cooked packages for that after every cook.

Build it once with the editor closed (a new module needs a full build); see `docs/UE-EDITOR-AUTOMATION.md`.
