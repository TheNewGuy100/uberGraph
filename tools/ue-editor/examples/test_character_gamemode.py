"""Compiles BP_TestCharacter, creates /Game/Test/BP_TestGameMode (default pawn = BP_TestCharacter) and sets it as the
game mode override of /Game/Maps/TestWorld. Run after test_character_base.py and the Tick graph (see docs).
Run: python tools/ue-editor/ue_remote.py --file tools/ue-editor/examples/test_character_gamemode.py
"""
import unreal

bp = unreal.load_asset('/Game/Test/BP_TestCharacter')
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_asset('/Game/Test/BP_TestCharacter')

GM = '/Game/Test/BP_TestGameMode'
if unreal.EditorAssetLibrary.does_asset_exist(GM):
    unreal.EditorAssetLibrary.delete_asset(GM)
factory = unreal.BlueprintFactory()
factory.set_editor_property('parent_class', unreal.GameModeBase)
gm = unreal.AssetToolsHelpers.get_asset_tools().create_asset('BP_TestGameMode', '/Game/Test', unreal.Blueprint, factory)
unreal.get_default_object(gm.generated_class()).set_editor_property('default_pawn_class', bp.generated_class())
unreal.BlueprintEditorLibrary.compile_blueprint(gm)
unreal.EditorAssetLibrary.save_asset(GM)

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level('/Game/Maps/TestWorld')
ws = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_world_settings()
ws.set_editor_property('default_game_mode', gm.generated_class())
les.save_current_level()
print('game mode override:', ws.get_editor_property('default_game_mode').get_name())
