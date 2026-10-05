"""Blender: preserve high mesh, unwrap low mesh, rebake original PBR maps."""
import argparse
import json
import sys
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def audit(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    report = dict(vertices=len(bm.verts), faces=len(bm.faces),
                  triangles=sum(len(f.verts)-2 for f in bm.faces),
                  boundary_edges=sum(e.is_boundary for e in bm.edges),
                  multi_face_edges=sum(len(e.link_faces)>2 for e in bm.edges),
                  zero_area_faces=sum(f.calc_area()<1e-20 for f in bm.faces))
    for edge in bm.edges:
        edge.select_set(edge.is_boundary or len(edge.link_faces)>2)
    bm.to_mesh(obj.data); bm.free()
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--retopo',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--minimum',type=int,required=True)
    parser.add_argument('--maximum',type=int,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    directory=Path(args.output); directory.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.source)
    high=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if not high: raise ValueError('No source mesh')
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.wm.obj_import(filepath=args.retopo)
    low=[o for o in bpy.context.selected_objects if o.type=='MESH']
    bpy.context.view_layer.objects.active=low[0]
    if len(low)>1: bpy.ops.object.join()
    low=bpy.context.view_layer.objects.active; low.name='LOW_Final'
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    extracted_vertices=len(low.data.vertices)
    decimated=False
    if extracted_vertices>args.maximum:
        modifier=low.modifiers.new('Budget reduction','DECIMATE')
        modifier.decimate_type='COLLAPSE'
        lo_ratio,hi_ratio=.001,1.0
        goal=(args.minimum+args.maximum)//2
        for _ in range(16):
            modifier.ratio=(lo_ratio+hi_ratio)/2
            bpy.context.view_layer.update()
            evaluated=low.evaluated_get(bpy.context.evaluated_depsgraph_get())
            count=len(evaluated.data.vertices)
            if abs(count-goal)<25: break
            if count>goal: hi_ratio=modifier.ratio
            else: lo_ratio=modifier.ratio
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        decimated=True
    bm=bmesh.new(); bm.from_mesh(low.data)
    coordinates=[v.co for v in bm.verts]
    scale=(Vector(tuple(max(v[i] for v in coordinates) for i in range(3)))-
           Vector(tuple(min(v[i] for v in coordinates) for i in range(3)))).length
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=scale*1e-7)
    loose=[v for v in bm.verts if not v.link_faces]
    if loose: bmesh.ops.delete(bm,geom=loose,context='VERTS')
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(low.data); bm.free()
    geometry=audit(low)
    if not args.minimum<=geometry['vertices']<=args.maximum:
        raise ValueError('Final geometric vertex budget exceeded: '+str(geometry))
    # Quantify shape deviation without claiming animation-ready topology.
    positions=[o.matrix_world@v.co for o in high for v in o.data.vertices]
    diagonal=(Vector(tuple(max(p[i] for p in positions) for i in range(3)))-
              Vector(tuple(min(p[i] for p in positions) for i in range(3)))).length
    trees=[]
    for obj in high:
        trees.append(BVHTree.FromPolygons([obj.matrix_world@v.co for v in obj.data.vertices],
                     [list(p.vertices) for p in obj.data.polygons]))
    distances=[]
    for v in low.data.vertices:
        hits=[t.find_nearest(low.matrix_world@v.co) for t in trees]
        distances.append(min(h[3] for h in hits if h[0] is not None))
    deviation=dict(mean_distance=sum(distances)/len(distances),maximum_distance=max(distances),
                   source_diagonal=diagonal,max_relative=max(distances)/diagonal)
    low_tree=BVHTree.FromPolygons([low.matrix_world@v.co for v in low.data.vertices],
                                 [list(p.vertices) for p in low.data.polygons])
    reverse=sorted(low_tree.find_nearest(p)[3] for p in positions)
    deviation['source_to_low_p95_relative']=reverse[int(.95*(len(reverse)-1))]/diagonal
    deviation['source_to_low_max_relative']=reverse[-1]/diagonal
    # Internal generated surfaces are not silhouette references. Sample the first
    # visible source hit from six orthographic directions instead.
    mins=[min(p[i] for p in positions) for i in range(3)]
    maxs=[max(p[i] for p in positions) for i in range(3)]
    visible=[]
    for axis in range(3):
        others=[i for i in range(3) if i!=axis]
        for sign in (-1,1):
            direction=Vector(tuple(-sign if i==axis else 0 for i in range(3)))
            for u in range(64):
                for v in range(64):
                    point=Vector()
                    point[axis]=(maxs[axis]+diagonal*.1) if sign==1 else (mins[axis]-diagonal*.1)
                    for i,t in zip(others,(u,v)):
                        point[i]=mins[i]+(maxs[i]-mins[i])*(t+.5)/64
                    hits=[t.ray_cast(point,direction) for t in trees]
                    hits=[h for h in hits if h[0] is not None]
                    if hits:
                        position=min(hits,key=lambda h:h[3])[0]
                        visible.append(low_tree.find_nearest(position)[3])
    visible.sort()
    if not visible: raise ValueError('No visible source samples')
    deviation['visible_source_samples']=len(visible)
    deviation['visible_source_to_low_p95_relative']=visible[int(.95*(len(visible)-1))]/diagonal
    deviation['visible_source_to_low_max_relative']=visible[-1]/diagonal
    if deviation['visible_source_to_low_p95_relative']>.015 or deviation['visible_source_to_low_max_relative']>.05:
        (directory/'shape_rejected.json').write_text(json.dumps(deviation,indent=2),encoding='utf-8')
        raise ValueError('Shape preservation failed: '+str(deviation))
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.151917,island_margin=.015)
    bpy.ops.object.mode_set(mode='OBJECT')
    target=bpy.data.materials.new('LOW_Baked'); target.use_nodes=True
    low.data.materials.clear(); low.data.materials.append(target)
    scene=bpy.context.scene; scene.render.engine='CYCLES'
    scene.cycles.device='CPU'; scene.cycles.samples=1
    scene.render.bake.use_selected_to_active=True
    scene.render.bake.use_clear=True; scene.render.bake.margin=16
    scene.render.bake.cage_extrusion=diagonal*.015
    scene.render.bake.max_ray_distance=diagonal*.08
    # Source geometry + maps are left unmodified on disk. Change shaders in memory only.
    original=[]
    for obj in high:
        for slot in obj.material_slots:
            mat=slot.material
            if mat and mat not in [x[0] for x in original]:
                principled=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
                base=principled.inputs['Base Color']
                color=base.links[0].from_socket if base.is_linked else None
                mr=next((n.outputs['Color'] for n in mat.node_tree.nodes if n.type=='TEX_IMAGE'
                         and n.image and n.image.colorspace_settings.name=='Non-Color'),None)
                original.append((mat,color,mr,list(base.default_value)))
    images={}
    for channel,filename in [('base','base_color_2048.png'),('mr','metallic_roughness_2048.png')]:
        for mat,color,mr,constant in original:
            nodes=mat.node_tree.nodes; links=mat.node_tree.links
            output=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
            emission=nodes.new('ShaderNodeEmission')
            socket=color if channel=='base' else mr
            if socket: links.new(socket,emission.inputs['Color'])
            else: emission.inputs['Color'].default_value=constant if channel=='base' else (0,1,0,1)
            links.new(emission.outputs[0],output.inputs['Surface'])
        image=bpy.data.images.new(filename,2048,2048,alpha=True)
        image.colorspace_settings.name='sRGB' if channel=='base' else 'Non-Color'
        node=target.node_tree.nodes.new('ShaderNodeTexImage'); node.image=image
        target.node_tree.nodes.active=node
        bpy.ops.object.select_all(action='DESELECT')
        for obj in high: obj.select_set(True)
        low.select_set(True); bpy.context.view_layer.objects.active=low
        bpy.ops.object.bake(type='EMIT')
        image.filepath_raw=str(directory/filename); image.file_format='PNG'; image.save()
        images[channel]=(image,node)
    principled=next(n for n in target.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    links=target.node_tree.links
    links.new(images['base'][1].outputs['Color'],principled.inputs['Base Color'])
    separate=target.node_tree.nodes.new('ShaderNodeSeparateColor')
    links.new(images['mr'][1].outputs['Color'],separate.inputs['Color'])
    links.new(separate.outputs['Green'],principled.inputs['Roughness'])
    links.new(separate.outputs['Blue'],principled.inputs['Metallic'])
    # Restore original source shaders in saved editable file.
    for mat,color,mr,constant in original:
        nodes=mat.node_tree.nodes
        principled_high=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        output=next(n for n in nodes if n.type=='OUTPUT_MATERIAL')
        mat.node_tree.links.new(principled_high.outputs['BSDF'],output.inputs['Surface'])
        for node in list(nodes):
            if node.type=='EMISSION': nodes.remove(node)
    bpy.ops.object.select_all(action='DESELECT'); low.select_set(True)
    bpy.context.view_layer.objects.active=low
    for obj in high:
        obj.name='HIGH_Source_'+obj.name; obj.hide_render=True; obj.hide_set(True)
    for image,node in images.values(): image.pack()
    bpy.ops.wm.save_as_mainfile(filepath=str(directory/'model_final.blend'))
    bpy.ops.export_scene.gltf(filepath=str(directory/'model_final.glb'),export_format='GLB',use_selection=True)
    report=dict(status='completed_review_required',geometry=geometry,deviation=deviation,
                method='Instant Meshes quad-dominant + Blender collapse reduction' if decimated else 'Instant Meshes quad-dominant',
                extracted_vertices=extracted_vertices,
                vertex_budget=[args.minimum,args.maximum],texture_size=2048,
                bake=dict(device='CPU',type='EMIT',ray_distance=diagonal*.08,extrusion=diagonal*.015,margin=16),
                limitations=['Joint edge flow/animation deformation needs manual review',
                             'Intersections not automatically removed',
                             'UV seams and ray misses require visual texture review',
                             'Geometric vertex budget differs from exported GLB vertex count'])
    (directory/'retopo_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__': main()
