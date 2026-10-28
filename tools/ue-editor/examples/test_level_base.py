"""Base of /Game/Maps/TestWorld: a floor to stand on, a PlayerStart and simple test lighting.

Idempotent: actors it creates carry the label prefix 'VP_' and are replaced on each run.
Run: python tools/ue-editor/ue_remote.py --file tools/ue-editor/examples/test_level_base.py
"""
import unreal

LEVEL = '/Game/Maps/TestWorld'
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
les.load_level(LEVEL)

for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith('VP_'):
        eas.destroy_actor(a)

def spawn(cls, label, loc=(0, 0, 0), rot=(0, 0, 0)):
    # rot is (pitch, yaw, roll); unreal.Rotator's positional order is (roll, pitch, yaw), so use keywords
    a = eas.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))
    a.set_actor_label(label)
    return a

# Floor: engine cube, 40 x 40 m, 1 m thick, top surface at Z = 0.
cube = unreal.load_asset('/Engine/BasicShapes/Cube')
floor = spawn(unreal.StaticMeshActor, 'VP_Floor', (0, 0, -50))
floor.static_mesh_component.set_static_mesh(cube)
floor.set_actor_scale3d(unreal.Vector(40, 40, 1))
# M_TestGrid comes from test_grid_material.py; fall back to the plain engine material
mat = (unreal.load_asset('/Game/Materials/M_TestGrid')
       or unreal.load_asset('/Engine/BasicShapes/BasicShapeMaterial'))
if mat:
    floor.static_mesh_component.set_material(0, mat)

spawn(unreal.PlayerStart, 'VP_PlayerStart', (0, 0, 100))

sun = spawn(unreal.DirectionalLight, 'VP_Sun', (0, 0, 500), (-50, 35, 0))
sun_c = sun.get_component_by_class(unreal.DirectionalLightComponent)
sun_c.set_mobility(unreal.ComponentMobility.MOVABLE)  # no baked lighting needed: nothing to rebuild
sun_c.set_editor_property('intensity', 8.0)
spawn(unreal.SkyAtmosphere, 'VP_SkyAtmosphere')
sky = spawn(unreal.SkyLight, 'VP_SkyLight', (0, 0, 300))
sky_c = sky.get_component_by_class(unreal.SkyLightComponent)
sky_c.set_mobility(unreal.ComponentMobility.MOVABLE)
sky_c.set_editor_property('real_time_capture', True)
spawn(unreal.ExponentialHeightFog, 'VP_Fog', (0, 0, 0))

les.save_current_level()
for a in eas.get_all_level_actors():
    print(a.get_class().get_name(), a.get_actor_label(), a.get_actor_location())
