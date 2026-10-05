import bpy,sys,json
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:];root,raw,out=map(Path,args)
bpy.ops.preferences.addon_enable(module='kimodo_rigify')
from kimodo_rigify import motion,retarget
bpy.ops.import_scene.fbx(filepath=str(root/'examples/rigged_avatar.fbx'))
rig=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
source=motion.import_raw(raw);action,pairs=retarget.bake(source,rig)
assert len(source.data.bones)==30
for f in range(1,61):
    bpy.context.scene.frame_set(f)
    for side in ('Left','Right'):
        assert rig.pose.bones['mixamorig:'+side+'ToeBase'].rotation_quaternion.angle<1e-5
source.hide_set(True);source.hide_render=True
assert any(i.has_data and tuple(i.size)==(2048,2048) for i in bpy.data.images)
bpy.context.scene.frame_set(30)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'generated_walk.blend'))
print('ACTUAL_MOTION_BAKE_PASS')
