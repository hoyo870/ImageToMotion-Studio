"""UI-only presentation; does not save or modify the generated file on disk."""
import bpy

def present():
    obj=bpy.data.objects.get('LOW_Final')
    if obj:
        bpy.ops.object.select_all(action='DESELECT')
        obj.hide_set(False); obj.select_set(True)
        bpy.context.view_layer.objects.active=obj
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.shading.type='MATERIAL'
                region=next((r for r in area.regions if r.type=='WINDOW'),None)
                if obj and region:
                    with bpy.context.temp_override(window=window,area=area,region=region):
                        bpy.ops.view3d.view_selected(use_all_regions=False)
    return None

bpy.app.timers.register(present,first_interval=1.0)
