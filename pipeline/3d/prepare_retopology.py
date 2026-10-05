"""Condition defective input for Instant Meshes; never replace textured source."""
import argparse, json, sys
from pathlib import Path
import bpy, bmesh
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from retopo_bake import audit
p=argparse.ArgumentParser(); p.add_argument('--source',required=True); p.add_argument('--output',required=True); p.add_argument('--voxel-fraction',type=float,default=.002)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
if not .001<=a.voxel_fraction<=.01: raise ValueError('voxel-fraction must be between .001 and .01')
out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.source)
objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
reports=[]
for obj in objects:
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    before=audit(obj)
    points=[v.co for v in obj.data.vertices]
    diagonal=(Vector(tuple(max(v[i] for v in points) for i in range(3)))-Vector(tuple(min(v[i] for v in points) for i in range(3)))).length
    voxel=diagonal*a.voxel_fraction
    # GLB splits vertices at UV/normal seams; weld before volumetric repair.
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=diagonal*1e-6)
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=diagonal*1e-7)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    modifier=obj.modifiers.new('Repair volume for retopology','REMESH')
    modifier.mode='VOXEL'; modifier.voxel_size=voxel; modifier.adaptivity=0
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    reports.append(dict(object=obj.name,before=before,after=audit(obj),voxel_size=voxel))
bpy.ops.object.select_all(action='DESELECT')
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active=objects[0]
bpy.ops.wm.obj_export(filepath=str(out/'retopo_input.obj'),export_selected_objects=True,export_materials=False,export_uv=False)
(out/'input_repair.json').write_text(json.dumps(dict(method='Blender voxel conditioning on geometry-only copy',objects=reports,
    limitations=['May close intended openings or merge gaps smaller than voxel size; inspect result',
                 'Original textured source remains bake source and is preserved']),indent=2),encoding='utf-8')
