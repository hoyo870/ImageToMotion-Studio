"""Blender background cleanup. Preserve source; export a separate review copy."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def boundaries(bm):
    remaining = {e for e in bm.edges if e.is_boundary}
    groups = []
    while remaining:
        stack = [remaining.pop()]
        edges = []
        while stack:
            edge = stack.pop()
            edges.append(edge)
            for vertex in edge.verts:
                for neighbor in vertex.link_edges:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
        groups.append(edges)
    return groups


def counts(bm):
    return dict(vertices=len(bm.verts), edges=len(bm.edges), faces=len(bm.faces),
                boundary_edges=sum(e.is_boundary for e in bm.edges),
                boundary_groups=len(boundaries(bm)),
                wire_edges=sum(e.is_wire for e in bm.edges),
                edges_with_more_than_two_faces=sum(len(e.link_faces) > 2 for e in bm.edges),
                zero_area_faces=sum(f.calc_area() <= 1e-20 for f in bm.faces))


def clean_object(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = counts(bm)
    coordinates = [v.co for v in bm.verts]
    low = Vector(tuple(min(p[i] for p in coordinates) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in coordinates) for i in range(3)))
    diagonal = (high-low).length
    if not math.isfinite(diagonal) or diagonal <= 0:
        bm.free()
        raise ValueError('Empty or invalid mesh bounds: '+obj.name)
    # Tiny tolerance: do not weld nearby fingers, hair clumps or garment layers.
    tolerance = diagonal * 1e-6
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=tolerance)
    welded_baseline = counts(bm)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=tolerance)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    filled = []
    retained = []
    # Edge count alone is insufficient: also constrain spatial extent/perimeter.
    for edges in boundaries(bm):
        edge_set = set(edges)
        vertices = {v for e in edges for v in e.verts}
        closed = all(sum(e in edge_set for e in v.link_edges) == 2 for v in vertices)
        extent = max((a.co-b.co).length for a in vertices for b in vertices) if len(edges) <= 6 else None
        perimeter = sum(e.calc_length() for e in edges)
        center = sum((v.co for v in vertices), Vector()) / len(vertices)
        item = dict(edges=len(edges), closed=closed, center=list(center),
                    extent=extent, perimeter=perimeter)
        if closed and 3 <= len(edges) <= 6 and extent <= diagonal*.002 and perimeter <= diagonal*.006:
            result = bmesh.ops.holes_fill(bm, edges=edges, sides=6)
            if result.get('faces'):
                item['faces_added'] = len(result['faces'])
                filled.append(item)
        else:
            retained.append(item)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    # Leave unresolved defects selected in the editable .blend for review.
    for v in bm.verts:
        v.select = False
    for e in bm.edges:
        e.select = e.is_boundary or len(e.link_faces) > 2
    for f in bm.faces:
        f.select = False
    bm.select_flush_mode()
    after = counts(bm)
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    return dict(object=obj.name, before=before, after_weld_before_repair=welded_baseline, after=after,
                merge_distance=tolerance, bounding_diagonal=diagonal,
                tiny_holes_filled=filled, retained_boundaries=retained,
                intersection_check='not performed; inspect intersecting/internal surfaces manually',
                normals='recalculated consistently; open components need orientation review',
                texture_rebake_required=bool(filled))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source = Path(args.input).resolve(strict=True)
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if destination == source.parent:
        raise ValueError('Cleanup must use a separate output directory')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and len(obj.data.vertices)]
    if not meshes:
        raise ValueError('No mesh in source GLB')
    reports = [clean_object(obj) for obj in meshes]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.wm.save_as_mainfile(filepath=str(destination/'model_cleaned.blend'))
    bpy.ops.export_scene.gltf(filepath=str(destination/'model_cleaned.glb'), export_format='GLB', use_selection=True)
    bpy.ops.wm.obj_export(filepath=str(destination/'geometry_for_retopology.obj'), export_selected_objects=True,
                          export_materials=False, export_uv=False, export_normals=True)
    report = dict(status='cleanup_completed_review_required', source=str(source), objects=reports,
                  limitations=['No retopology or target vertex reduction in this stage',
                               'No automatic removal of separate hair, clothing or accessories',
                               'Large openings, intersections and open-shell normal directions require review',
                               'Original UVs retained where possible; filled faces require texture rebaking'])
    (destination/'cleanup_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (destination/'REVIEW.txt').write_text(
        '자동 메시 정리 완료 (원본 보존)\n'
        'model_cleaned.blend: 편집용. 남은 열린 경계/다중 연결 엣지는 선택 표시.\n'
        'model_cleaned.glb: 기존 텍스처를 유지한 검토용 복사본.\n'
        'geometry_for_retopology.obj: 리토폴로지 입력용 형상.\n'
        '작은 구멍을 채운 새 면의 UV/텍스처는 재베이킹 필요.\n'
        '큰 구멍, 교차/내부 면, 열린 부분의 노멀 방향은 수동 검토 필요.\n'
        '리토폴로지 및 목표 버텍스 감소는 이 정리 단계에 포함하지 않음.\n', encoding='utf-8')


if __name__ == '__main__':
    main()
