"""Real Blender subdivision regression: preserve shape/volume and vertex ranges."""
import sys
from pathlib import Path
import bpy,bmesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipeline/3d'))
from retopo_bake import supplement_vertices

for minimum,maximum in ((1000,1500),(2000,3000)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj=bpy.context.object
    bm=bmesh.new(); bm.from_mesh(obj.data); volume=bm.calc_volume(); bm.free()
    added,geometry=supplement_vertices(obj,minimum,maximum)
    assert minimum<=geometry['vertices']<=maximum
    assert geometry['boundary_edges']==geometry['multi_face_edges']==geometry['zero_area_faces']==0
    bm=bmesh.new(); bm.from_mesh(obj.data)
    assert abs(bm.calc_volume()-volume)<1e-6
    assert all(abs(max(abs(v.co[i]) for i in range(3))-1)<1e-6 for v in bm.verts)
    bm.free()
    print('BUDGET_OK',minimum,geometry['vertices'],added,flush=True)
