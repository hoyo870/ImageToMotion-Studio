"""SOMA 30관절과 공식 BVH를 Blender 소스 Armature로 가져온다."""
import bpy
from mathutils import Matrix, Vector, Quaternion
from pathlib import Path
import json
import struct
from .backend import read_raw

C = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def skeleton():
    return json.loads(Path(__file__).with_name('soma30.json').read_text(encoding='utf-8'))


def select_only(obj):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def import_bvh(path, frame_start=1):
    previous = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=str(path), target='ARMATURE', global_scale=0.01,
        frame_start=frame_start, update_scene_fps=True, update_scene_duration=True,
        axis_forward='-Z', axis_up='Y')
    objects = [o for o in bpy.data.objects if o not in previous and o.type == 'ARMATURE']
    if len(objects) != 1 or 'Hips' not in objects[0].pose.bones:
        raise RuntimeError('SOMA BVH 골격을 확인할 수 없습니다.')
    obj = objects[0]
    obj.name = 'Kimodo_SOMA77_' + Path(path).stem
    obj['kimodo_source'] = 'OFFICIAL'
    return obj


def import_raw(folder, frame_start=1):
    positions, rotations = read_raw(folder)
    return build_soma(positions, rotations, Path(folder).parent.name, frame_start)


def build_soma(positions, rotations, name, frame_start=1):
    spec = skeleton()
    names, parents, offsets = spec['names'], spec['parents'], spec['offsets']
    count = len(positions) // 3
    if count < 1 or len(rotations) != count * 30 * 4:
        raise ValueError('SOMA 모션 프레임/회전 수가 맞지 않습니다.')
    rest = []
    for i, offset in enumerate(offsets):
        local = Matrix.Translation(Vector(offset))
        rest.append(local if parents[i] < 0 else rest[parents[i]] @ local)
    data = bpy.data.armatures.new('Kimodo_SOMA30')
    obj = bpy.data.objects.new('Kimodo_SOMA30_' + name, data)
    bpy.context.collection.objects.link(obj)
    select_only(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    for i, joint in enumerate(names):
        bone = data.edit_bones.new(joint)
        bone.head = (C @ rest[i]).translation
        children = [j for j, p in enumerate(parents) if p == i]
        if children:
            bone.tail = (C @ rest[children[0]]).translation
        else:
            bone.tail = bone.head + Vector((0, 0, 0.055))
        if (bone.tail - bone.head).length < 0.001:
            bone.tail = bone.head + Vector((0, 0, 0.055))
        if parents[i] >= 0:
            bone.parent = data.edit_bones[names[parents[i]]]
        bone.use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.show_in_front = True
    obj['kimodo_source'] = 'CPP'
    obj.animation_data_create()
    obj.animation_data.action = bpy.data.actions.new('Kimodo_SOMA30_' + name)
    obj.animation_data.action.use_fake_user = True
    bone_rest = [data.bones[n].matrix_local.copy() for n in names]
    inverse_rest = [(C @ m @ C.inverted()).inverted() for m in rest]
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    for f in range(count):
        scene.frame_set(frame_start + f)
        transforms = []
        for i, joint in enumerate(names):
            xyzw = rotations[(f * 30 + i) * 4:(f * 30 + i + 1) * 4]
            q = Quaternion((xyzw[3], xyzw[0], xyzw[1], xyzw[2]))
            if abs(q.magnitude - 1) > 0.02:
                raise ValueError('SOMA 회전이 정규화되어 있지 않습니다.')
            q.normalize()
            translation = positions[f * 3:f * 3 + 3] if i == 0 else offsets[i]
            local = Matrix.Translation(Vector(translation)) @ q.to_matrix().to_4x4()
            world = local if parents[i] < 0 else transforms[parents[i]] @ local
            transforms.append(world)
            pb = obj.pose.bones[joint]
            pb.rotation_mode = 'QUATERNION'
            pb.matrix = C @ world @ C.inverted() @ inverse_rest[i] @ bone_rest[i]
            bpy.context.view_layer.update()
            pb.keyframe_insert('location', frame=frame_start + f, group=joint)
            pb.keyframe_insert('rotation_quaternion', frame=frame_start + f, group=joint)
    scene.frame_start, scene.frame_end = frame_start, frame_start + count - 1
    scene.frame_set(frame_start)
    return obj


def import_glb(path, frame_start=1):
    # Kimodo.cpp의 노드 전용 GLB만 읽는다. 캐릭터 GLB는 일반 Blender 가져오기를 사용한다.
    raw = Path(path).read_bytes()
    if len(raw) < 20 or struct.unpack_from('<III', raw) != (0x46546c67, 2, len(raw)):
        raise ValueError('유효한 GLB 2.0 파일이 아닙니다.')
    size, kind = struct.unpack_from('<II', raw, 12)
    if kind != 0x4e4f534a:
        raise ValueError('GLB JSON 청크가 없습니다.')
    doc = json.loads(raw[20:20 + size])
    binary_offset = 20 + size
    if len(raw) < binary_offset + 8:
        raise ValueError('GLB 바이너리 청크가 없습니다.')
    length, kind = struct.unpack_from('<II', raw, binary_offset)
    if kind != 0x004e4942:
        raise ValueError('GLB 바이너리 청크 형식 오류')
    binary = raw[binary_offset + 8:binary_offset + 8 + length]
    def accessor(index):
        a = doc['accessors'][index]
        v = doc['bufferViews'][a['bufferView']]
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[a['type']]
        if a['componentType'] != 5126 or 'sparse' in a:
            raise ValueError('지원하지 않는 GLB 데이터 형식')
        start = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = v.get('byteStride', width * 4)
        return [struct.unpack_from('<' + 'f' * width, binary, start + i * stride)
                for i in range(a['count'])]
    spec = skeleton()
    names = [n.get('name', '') for n in doc['nodes']]
    if set(names) != set(spec['names']) or len(names) != 30:
        raise ValueError('Kimodo.cpp SOMA 30관절 GLB만 지원합니다.')
    anim = doc['animations'][0]
    times = None
    values = {}
    for channel in anim['channels']:
        sampler = anim['samplers'][channel['sampler']]
        t = accessor(sampler['input'])
        if times is not None and t != times:
            raise ValueError('관절별 시간이 다른 GLB는 지원하지 않습니다.')
        times = t
        values[names[channel['target']['node']], channel['target']['path']] = accessor(sampler['output'])
    count = len(times or [])
    for i, t in enumerate(times or []):
        if abs(t[0] - i / 30) > 1e-4:
            raise ValueError('30fps가 아닌 GLB는 지원하지 않습니다.')
    positions = [v for row in values['Hips', 'translation'] for v in row]
    rotations = [v for f in range(count) for name in spec['names']
                 for v in values[name, 'rotation'][f]]
    return build_soma(positions, rotations, Path(path).parent.name, frame_start)
