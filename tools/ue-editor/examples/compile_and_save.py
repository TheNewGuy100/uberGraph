# Example: compile a Blueprint and save its asset through editor Python (run via ../ue_remote.py --file).
import unreal
BP = '/Game/Widgets/WidgetVanillaPlusMonitor'
bp = unreal.load_asset(BP)
try:
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    print('compiled')
except Exception as e:
    print('compile failed:', type(e).__name__, str(e)[:200])
print('saved:', unreal.EditorAssetLibrary.save_asset(BP, only_if_is_dirty=False))
print('exists:', unreal.EditorAssetLibrary.does_asset_exist(BP))
