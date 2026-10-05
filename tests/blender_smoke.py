import bpy
import sys
import json
from pathlib import Path
root = Path(sys.argv[sys.argv.index('--') + 1])
bpy.ops.preferences.addon_enable(module='kimodo_rigify')
bpy.ops.preferences.addon_enable(module='mixamo_rig')
bpy.ops.preferences.addon_enable(module='rigify')
assert bpy.context.preferences.addons.get('rigify')
from kimodo_rigify import motion, retarget, backend
backend.validate(root / 'runtime', 'CPP')
bpy.ops.import_scene.fbx(filepath=str(root / 'examples/rigged_avatar.fbx'))
target = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
source = motion.build_soma([0,0,0, 0,0,.01], [0,0,0,1]*60, 'Installer_Smoke')
action, pairs = retarget.bake(source, target)
assert action['kimodo_soma30_extremity_rest']
for frame in (1,2):
    bpy.context.scene.frame_set(frame)
    for side in ('Left','Right'):
        assert target.pose.bones['mixamorig:'+side+'ToeBase'].rotation_quaternion.angle < 1e-5
assert 'mr_control_rig' not in target.data
motion.select_only(target)
assert bpy.ops.mr.make_rig(bake_anim=True, ik_arms=False, ik_legs=False) == {'FINISHED'}
assert 'mr_control_rig' in target.data
images = [i for i in bpy.data.images if i.has_data and i.size[0] == 2048]
assert images, 'Texture not imported'
(root/'.state/blender_smoke.json').write_text(json.dumps({
    'passed':True,'blender':bpy.app.version_string,'kimodo':retarget.__file__,
    'mixamo_control_rig':True,'texture_2048':True,'soma30_toes':True},indent=2),encoding='utf-8')
print('BLENDER_SMOKE_PASS')
