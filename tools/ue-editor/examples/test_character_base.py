"""Creates /Game/Test/BP_TestCharacter: components and movement numbers measured in the game (analysis/CHARACTER-PROBE.md).

Only the data part (capsule, CharacterMovement, camera). Key events are added by the Blueprint DSL (test_character_input.dsl).
Re-running deletes and rebuilds the asset. Test pawn for TestWorld only, never cooked for the game.
Run: python tools/ue-editor/ue_remote.py --file tools/ue-editor/examples/test_character_base.py
"""
import unreal

PATH, NAME = '/Game/Test', 'BP_TestCharacter'
ASSET = f'{PATH}/{NAME}'
EYE_HEIGHT = 64.0

if unreal.EditorAssetLibrary.does_asset_exist(ASSET):
    unreal.EditorAssetLibrary.delete_asset(ASSET)
factory = unreal.BlueprintFactory()
factory.set_editor_property('parent_class', unreal.Character)
bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, PATH, unreal.Blueprint, factory)

# Camera component under the capsule (root).
sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
lib = unreal.SubobjectDataBlueprintFunctionLibrary
handles = sub.k2_gather_subobject_data_for_blueprint(bp)
root = handles[0]
params = unreal.AddNewSubobjectParams(parent_handle=root, new_class=unreal.CameraComponent, blueprint_context=bp)
cam_handle, fail = sub.add_new_subobject(params)
sub.rename_subobject(cam_handle, 'EyeCamera')
unreal.BlueprintEditorLibrary.compile_blueprint(bp)

# Defaults live on the class default object and on the component templates.
cdo = unreal.get_default_object(bp.generated_class())
for h in sub.k2_gather_subobject_data_for_blueprint(bp):
    d = sub.k2_find_subobject_data_from_handle(h)
    obj = lib.get_object(d)
    if isinstance(obj, unreal.CapsuleComponent):
        obj.set_editor_property('capsule_radius', 30.0)
        obj.set_editor_property('capsule_half_height', 100.0)
    elif isinstance(obj, unreal.CameraComponent):
        obj.set_editor_property('field_of_view', 120.0)
        obj.set_editor_property('use_pawn_control_rotation', True)
        obj.set_editor_property('relative_location', unreal.Vector(0, 0, EYE_HEIGHT))
    elif isinstance(obj, unreal.CharacterMovementComponent):
        for k, v in dict(max_walk_speed=510.0, max_walk_speed_crouched=200.0, max_acceleration=2048.0,
                         braking_deceleration_walking=2048.0, braking_friction_factor=2.0, ground_friction=8.0,
                         braking_friction=0.0, jump_z_velocity=440.0, gravity_scale=1.0, air_control=0.4,
                         falling_lateral_friction=0.0, max_step_height=45.0, walkable_floor_angle=55.0,
                         crouched_half_height=70.0, mass=100.0, rotation_rate=unreal.Rotator(0, 0, 360)).items():
            obj.set_editor_property(k, v)
        obj.set_editor_property('nav_agent_props', obj.get_editor_property('nav_agent_props'))
cdo.set_editor_property('base_eye_height', EYE_HEIGHT)
cdo.set_editor_property('use_controller_rotation_yaw', True)
cdo.set_editor_property('use_controller_rotation_pitch', False)

unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_asset(ASSET)
print('created', bp.get_path_name(), 'camera failure reason:', fail)
