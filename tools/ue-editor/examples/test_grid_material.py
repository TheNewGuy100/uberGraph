"""Creates /Game/Materials/M_TestGrid: a world-aligned grid (1 tile = TILE_CM) for judging scale and distance.

Uses the engine's DefaultWhiteGrid texture sampled with world X/Y, so any mesh shows the same grid size.
Parameters: Tint (vector), TileCm (scalar). Re-running rebuilds the material from scratch.
Run: python tools/ue-editor/ue_remote.py --file tools/ue-editor/examples/test_grid_material.py
"""
import unreal

PATH, NAME = '/Game/Materials', 'M_TestGrid'
TILE_CM = 100.0
mel = unreal.MaterialEditingLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()

if unreal.EditorAssetLibrary.does_asset_exist(f'{PATH}/{NAME}'):
    unreal.EditorAssetLibrary.delete_asset(f'{PATH}/{NAME}')
mat = at.create_asset(NAME, PATH, unreal.Material, unreal.MaterialFactoryNew())

def node(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)

wp = node(unreal.MaterialExpressionWorldPosition, -900, 0)
mask = node(unreal.MaterialExpressionComponentMask, -700, 0)
mask.set_editor_property('r', True); mask.set_editor_property('g', True)
mask.set_editor_property('b', False); mask.set_editor_property('a', False)
tile = node(unreal.MaterialExpressionScalarParameter, -900, 200)
tile.set_editor_property('parameter_name', 'TileCm'); tile.set_editor_property('default_value', TILE_CM)
div = node(unreal.MaterialExpressionDivide, -500, 0)
tex = node(unreal.MaterialExpressionTextureSampleParameter2D, -300, 0)
tex.set_editor_property('parameter_name', 'GridTexture')
tex.set_editor_property('texture', unreal.load_asset('/Engine/EngineMaterials/DefaultWhiteGrid'))
tint = node(unreal.MaterialExpressionVectorParameter, -300, 250)
tint.set_editor_property('parameter_name', 'Tint')
tint.set_editor_property('default_value', unreal.LinearColor(0.6, 0.6, 0.6, 1.0))
mul = node(unreal.MaterialExpressionMultiply, -50, 100)
rough = node(unreal.MaterialExpressionConstant, -50, 300)
rough.set_editor_property('r', 0.85)

mel.connect_material_expressions(wp, '', mask, '')
mel.connect_material_expressions(mask, '', div, 'A')
mel.connect_material_expressions(tile, '', div, 'B')
mel.connect_material_expressions(div, '', tex, 'UVs')
mel.connect_material_expressions(tex, 'RGB', mul, 'A')
mel.connect_material_expressions(tint, '', mul, 'B')
mel.connect_material_property(mul, '', unreal.MaterialProperty.MP_BASE_COLOR)
mel.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)

mel.recompile_material(mat)
unreal.EditorAssetLibrary.save_asset(f'{PATH}/{NAME}')
print('created', mat.get_path_name())
