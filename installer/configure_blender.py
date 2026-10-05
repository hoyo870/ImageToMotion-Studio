import bpy
import sys
from pathlib import Path
runtime = Path(sys.argv[sys.argv.index('--') + 1])
bpy.ops.preferences.addon_enable(module='kimodo_rigify')
bpy.ops.preferences.addon_enable(module='mixamo_rig')
bpy.ops.preferences.addon_enable(module='rigify')
bpy.context.preferences.addons['kimodo_rigify'].preferences.install_root = str(runtime)
bpy.context.scene.kimodo.backend = 'CPP'
bpy.ops.wm.save_userpref()
print('BLENDER_PROFILE_READY', runtime)
