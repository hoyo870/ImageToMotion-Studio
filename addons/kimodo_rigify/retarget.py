"""SOMA 소스에서 표준 Rigify FK 컨트롤로 새 Action을 베이크한다."""
import bpy
import json
import math
from mathutils import Matrix, Vector, Quaternion

BODY = [('hips', 'Hips'), ('chest', 'Chest'), ('spine_fk', 'Spine1'),
        ('spine_fk.001', 'Spine2'), ('spine_fk.002', 'Chest'),
        ('spine_fk.003', 'Chest'), ('neck', 'Neck1'), ('head', 'Head')]
for side, prefix in [('L', 'Left'), ('R', 'Right')]:
    BODY += [(f'shoulder.{side}', prefix + 'Shoulder'),
             (f'upper_arm_fk.{side}', prefix + 'Arm'),
             (f'forearm_fk.{side}', prefix + 'ForeArm'),
             (f'hand_fk.{side}', prefix + 'Hand'),
             (f'thigh_fk.{side}', prefix + 'Leg'),
             (f'shin_fk.{side}', prefix + 'Shin'),
             (f'foot_fk.{side}', prefix + 'Foot'),
             (f'toe_fk.{side}', prefix + 'ToeBase')]


def mixamo_names(target):
    names = {}
    for name in target.pose.bones.keys():
        canonical = name.rsplit(':', 1)[-1]
        if canonical.lower().startswith('mixamorig'):
            canonical = canonical[9:]
        key = canonical.casefold()
        if key in names:
            raise ValueError('중복된 Mixamo 본 이름: ' + canonical)
        names[key] = name
    return names


def target_kind(target):
    if all(n in target.pose.bones for n in ('root','torso','hips','chest','upper_arm_fk.L','upper_arm_fk.R','thigh_fk.L','thigh_fk.R')):
        return 'RIGIFY'
    names = mixamo_names(target)
    required = ['Hips','Spine','Spine1','Spine2','Head']
    for side in ('Left','Right'):
        required += [side+n for n in ('Arm','ForeArm','Hand','UpLeg','Leg','Foot')]
    missing = [n for n in required if n.casefold() not in names]
    if missing:
        raise ValueError('지원하는 Rigify 또는 Mixamo 리그가 아닙니다. Mixamo 필수 본 누락: '+', '.join(missing))
    return 'MIXAMO'


def validate_target(target):
    if target is None or target.type != 'ARMATURE':
        raise ValueError('리타게팅 대상 Rigify 또는 Mixamo Armature를 선택하세요.')
    if target.library or target.data.library:
        raise ValueError('링크된 리그는 먼저 Library Override 또는 로컬 사본을 만드세요.')
    target_kind(target)
    if max(target.scale) - min(target.scale) > 1e-4 or min(target.scale) <= 0:
        raise ValueError('대상 리그는 양수 균일 스케일이어야 합니다.')
    return target


def mappings(source, target, fingers=True):
    if target_kind(target) == 'MIXAMO':
        names = mixamo_names(target)
        pairs = [('Hips','Hips'),('Spine','Spine1'),('Spine1','Spine2'),
                 ('Spine2','Chest'),('Neck','Neck1'),('Head','Head')]
        for side in ('Left','Right'):
            pairs += [(side+t,side+s) for t,s in [('Shoulder','Shoulder'),('Arm','Arm'),
                      ('ForeArm','ForeArm'),('Hand','Hand'),('UpLeg','Leg'),
                      ('Leg','Shin'),('Foot','Foot'),('ToeBase','ToeBase')]]
            if fingers:
                for finger in ('Thumb','Index','Middle','Ring','Pinky'):
                    pairs += [(f'{side}Hand{finger}{i}',f'{side}Hand{finger}{i if finger=="Thumb" else i+1}') for i in range(1,4)]
        return [(names[t.casefold()],s) for t,s in pairs if t.casefold() in names and s in source.pose.bones]
    pairs = list(BODY)
    if fingers:
        for side, prefix in [('L', 'Left'), ('R', 'Right')]:
            for label, name in [('Thumb', 'thumb'), ('Index', 'f_index'),
                                ('Middle', 'f_middle'), ('Ring', 'f_ring'), ('Pinky', 'f_pinky')]:
                for segment in range(1, 4):
                    source_segment = segment if label == 'Thumb' else segment + 1
                    pairs.append((f'{name}.{segment:02}.{side}',
                                  f'{prefix}Hand{label}{source_segment}'))
    return [(t, s) for t, s in pairs if t in target.pose.bones and s in source.pose.bones]


def depth(pb):
    return len(pb.parent_recursive)


def soma30_extremity_rest(source, target, fingers=True):
    """CPP terminal toe axes are synthetic; keep target rest toes instead.

    SOMA30 contains no finger joints. Supply a mild rest curl, never replace
    detailed SOMA77 finger animation or the generated wrist motion.
    """
    if source.get('kimodo_source') != 'CPP' or len(source.data.bones) != 30:
        return {}
    mixamo = target_kind(target) == 'MIXAMO'
    names = mixamo_names(target) if mixamo else {}
    rotations = {}
    down = target.matrix_world.to_quaternion().inverted() @ Vector((0, 0, -1))
    for side, suffix in (('Left', 'L'), ('Right', 'R')):
        toe = names.get((side+'ToeBase').casefold()) if mixamo else 'toe_fk.'+suffix
        if toe and toe in target.pose.bones:
            rotations[toe] = Quaternion()
        if not fingers:
            continue
        for finger, label in (('Index','f_index'), ('Middle','f_middle'),
                              ('Ring','f_ring'), ('Pinky','f_pinky')):
            for segment, degrees in ((1,8), (2,12), (3,8)):
                name = (names.get(f'{side}Hand{finger}{segment}'.casefold()) if mixamo
                        else f'{label}.{segment:02}.{suffix}')
                if not name or name not in target.pose.bones:
                    continue
                bone = target.data.bones[name]
                axis = (bone.tail_local-bone.head_local).normalized().cross(down)
                if axis.length < 1e-6:
                    continue
                local_axis = bone.matrix_local.to_quaternion().inverted() @ axis.normalized()
                rotations[name] = Quaternion(local_axis, math.radians(degrees))
    return rotations


def roll_correction(source_rest, target_rest):
    # 소스 뼈의 실제 방향을 보존하며 대상의 롤 차이만 보정한다.
    source_q, target_q = source_rest.to_quaternion(), target_rest.to_quaternion()
    sy, ty = source_q @ Vector((0, 1, 0)), target_q @ Vector((0, 1, 0))
    swing = sy.rotation_difference(ty)
    return source_q.inverted() @ swing.inverted() @ target_q


def validate_append(target, start):
    validate_target(target)
    previous = target.animation_data.action if target.animation_data else None
    if previous is None or 'kimodo_source' not in previous:
        raise ValueError('이어 붙이려면 대상에 기존 Kimodo Action이 있어야 합니다.')
    expected = int(previous.frame_range[1]) + 1
    if start != expected:
        raise ValueError(f'이어 붙이기 시작 프레임은 {expected}이어야 합니다. 다음 구간 버튼을 사용하세요.')
    return previous


def bake(source, target, frame_start=None, frame_end=None, root_motion=True, fingers=True, append=False):
    validate_target(target)
    kind = target_kind(target)
    mixamo = kind == 'MIXAMO'
    names = mixamo_names(target) if mixamo else {}
    root_name = names['hips'] if mixamo else 'root'
    if source is target or source.type != 'ARMATURE' or 'Hips' not in source.pose.bones:
        raise ValueError('대상과 다른 SOMA 소스 Armature가 필요합니다.')
    if not source.animation_data or not source.animation_data.action:
        raise ValueError('소스 Armature에 애니메이션 Action이 없습니다.')
    action = source.animation_data.action
    start = int(frame_start if frame_start is not None else action.frame_range[0])
    end = int(frame_end if frame_end is not None else action.frame_range[1])
    if end < start or end - start > 3000:
        raise ValueError('리타게팅 범위는 1~3001프레임이어야 합니다.')
    if append:
        validate_append(target, start)
    pairs = mappings(source, target, fingers)
    if len(pairs) < 18:
        raise ValueError('몸통/팔/다리 자동 매핑이 부족합니다. SOMA 골격을 확인하세요.')
    extremity_rest = soma30_extremity_rest(source, target, fingers)
    pairs = [(t, s) for t, s in pairs if t not in extremity_rest]
    pairs.sort(key=lambda pair: depth(target.pose.bones[pair[0]]))
    scene = bpy.context.scene
    original_frame = scene.frame_current
    old_range = [scene.frame_start, scene.frame_end]
    target.animation_data_create()
    previous = target.animation_data.action
    if previous:
        previous.use_fake_user = True
    # 기존 NLA가 새 베이크 결과를 혼합하지 않도록 베이크 중에만 비활성화한다.
    old_use_nla = target.animation_data.use_nla
    target.animation_data.use_nla = False
    # 기존 Action의 키를 복사하여 앞 구간을 그대로 보존한다.
    created = previous.copy() if append else bpy.data.actions.new('Kimodo_'+kind.title()+'_' + action.name)
    created.name = ('Kimodo_Sequence_' if append else 'Kimodo_'+kind.title()+'_') + action.name
    created.use_fake_user = True
    target.animation_data.action = created
    old_basis = {pb.name: pb.matrix_basis.copy() for pb in target.pose.bones}
    old_modes = {pb.name: pb.rotation_mode for pb in target.pose.bones}
    old_props = {}
    try:
        root_offset = Vector((0, 0, 0))
        previous_quat = {}
        if append:
            scene.frame_set(start - 1)
            bpy.context.view_layer.update()
            root_offset = target.pose.bones[root_name].location.copy()
            previous_quat = {name: target.pose.bones[name].rotation_quaternion.copy() for name, _ in pairs}
        for pb in target.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
            for key in ('IK_FK', 'FK_limb_follow'):
                if key in pb and not mixamo:
                    old_props[pb.name, key] = pb[key]
                    pb[key] = 1.0 if key == 'IK_FK' else 0.0
        scene.frame_set(start)
        bpy.context.view_layer.update()
        corrections = {t: roll_correction(source.data.bones[s].matrix_local,
                                          target.data.bones[t].matrix_local) for t, s in pairs}
        if mixamo:
            corrections = {t: roll_correction(source.matrix_world @ source.data.bones[s].matrix_local,
                                               target.matrix_world @ target.data.bones[t].matrix_local) for t,s in pairs}
        initial_root = source.pose.bones['Hips'].head.copy()
        source_length = sum((source.data.bones[n].tail_local - source.data.bones[n].head_local).length
                            for n in ('LeftLeg', 'LeftShin'))
        target_length = sum((target.data.bones[n].tail_local - target.data.bones[n].head_local).length
                            for n in ((names['leftupleg'],names['leftleg']) if mixamo else ('thigh_fk.L', 'shin_fk.L')))
        scale = target_length / max(source_length, 1e-6)
        if mixamo:
            source_length = sum((source.matrix_world.to_3x3() @ (source.data.bones[n].tail_local-source.data.bones[n].head_local)).length for n in ('LeftLeg','LeftShin'))
            target_length = sum((target.matrix_world.to_3x3() @ (target.data.bones[n].tail_local-target.data.bones[n].head_local)).length for n in (names['leftupleg'],names['leftleg']))
            scale = target_length/max(source_length,1e-6)
        prev_quat = previous_quat
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            # 매 프레임 레스트 기준에서 시작하여 누적 오차를 막는다.
            for pb in target.pose.bones:
                pb.matrix_basis = Matrix.Identity(4)
            for (name, key) in old_props:
                target.pose.bones[name][key] = 1.0 if key == 'IK_FK' else 0.0
                target.pose.bones[name].keyframe_insert(f'["{key}"]', frame=frame, group=name)
            bpy.context.view_layer.update()
            root = target.pose.bones[root_name]
            if root_motion:
                delta_position = (source.pose.bones['Hips'].head - initial_root) * scale
                if mixamo:
                    delta_position = target.matrix_world.to_3x3().inverted() @ (source.matrix_world.to_3x3() @ delta_position)
                root.location = root_offset + root.bone.matrix_local.to_3x3().inverted() @ delta_position
            else:
                root.location = root_offset
            root.keyframe_insert('location', frame=frame, group=root_name)
            bpy.context.view_layer.update()
            for target_name, source_name in pairs:
                pb, sp = target.pose.bones[target_name], source.pose.bones[source_name]
                if mixamo:
                    source_world = source.matrix_world.to_quaternion()
                    target_world = target.matrix_world.to_quaternion()
                    if source_name in ('Hips','Spine1','Spine2','Chest','Neck1','Head'):
                        delta = (source_world @ sp.matrix.to_quaternion()) @ (source_world @ source.data.bones[source_name].matrix_local.to_quaternion()).inverted()
                        rotation = target_world.inverted() @ delta @ target_world @ target.data.bones[target_name].matrix_local.to_quaternion()
                    else:
                        rotation = target_world.inverted() @ source_world @ sp.matrix.to_quaternion() @ corrections[target_name]
                elif target_name in ('hips', 'chest') or target_name.startswith('spine_fk'):
                    delta = sp.matrix.to_quaternion() @ source.data.bones[source_name].matrix_local.to_quaternion().inverted()
                    rotation = delta @ target.data.bones[target_name].matrix_local.to_quaternion()
                else:
                    rotation = sp.matrix.to_quaternion() @ corrections[target_name]
                desired = Matrix.LocRotScale(pb.matrix.translation, rotation, Vector((1, 1, 1)))
                local = target.convert_space(pose_bone=pb, matrix=desired, from_space='POSE', to_space='LOCAL')
                q = local.to_quaternion()
                if target_name in prev_quat:
                    q.make_compatible(prev_quat[target_name])
                prev_quat[target_name] = q.copy()
                pb.rotation_mode = 'QUATERNION'
                pb.rotation_quaternion = q
                pb.keyframe_insert('rotation_quaternion', frame=frame, group=target_name)
                bpy.context.view_layer.update()
            for name, rotation in extremity_rest.items():
                pb = target.pose.bones[name]
                pb.rotation_mode = 'QUATERNION'
                q = rotation.copy()
                if name in prev_quat:
                    q.make_compatible(prev_quat[name])
                prev_quat[name] = q.copy()
                pb.rotation_quaternion = q
                pb.keyframe_insert('rotation_quaternion', frame=frame, group=name)
            bpy.context.view_layer.update()
        created['kimodo_source'] = source.name
        created['kimodo_soma30_extremity_rest'] = ', '.join(extremity_rest)
        created['kimodo_target_type'] = kind
        created['kimodo_root_motion'] = root_motion
        created['kimodo_mapping'] = ', '.join(f'{s}->{t}' for t, s in pairs)
        segments = json.loads(previous.get('kimodo_segments', '[]')) if append else []
        if append and not segments:
            segments.append({'source': previous.get('kimodo_source', ''),
                             'start': int(previous.frame_range[0]), 'end': int(previous.frame_range[1])})
        segments.append({'source': source.name, 'start': start, 'end': end})
        created['kimodo_segments'] = json.dumps(segments)
        created['kimodo_restore_state'] = json.dumps({'action': previous.name if previous else None,
            'use_nla': old_use_nla, 'basis': {name: [list(row) for row in matrix] for name, matrix in old_basis.items()},
            'modes': old_modes, 'properties': [[name, key, value] for (name, key), value in old_props.items()],
            'timeline': [int(previous.frame_range[0]), int(previous.frame_range[1])] if append else old_range})
        scene.frame_start, scene.frame_end = int(created.frame_range[0]), int(created.frame_range[1])
        # 새 Action 단독으로 재생한다. 기존 NLA 트랙 자체와 Action은 보존한다.
        created['kimodo_previous_use_nla'] = old_use_nla
        scene.frame_set(start)
        bpy.context.view_layer.update()
        return created, pairs
    except Exception:
        target.animation_data.action = previous
        target.animation_data.use_nla = old_use_nla
        for name, value in old_basis.items():
            target.pose.bones[name].rotation_mode = old_modes[name]
            target.pose.bones[name].matrix_basis = value
        for (name, key), value in old_props.items():
            target.pose.bones[name][key] = value
        created.use_fake_user = False
        bpy.data.actions.remove(created)
        raise
    finally:
        scene.frame_set(original_frame)


def restore_previous(target):
    validate_target(target)
    current = target.animation_data.action if target.animation_data else None
    if not current or 'kimodo_restore_state' not in current:
        raise ValueError('현재 Action에 Kimodo 이전 상태 기록이 없습니다.')
    state = json.loads(current['kimodo_restore_state'])
    previous = bpy.data.actions.get(state['action']) if state['action'] else None
    if state['action'] and previous is None:
        raise ValueError('이전 Action이 삭제되어 복원할 수 없습니다.')
    target.animation_data.action = previous
    target.animation_data.use_nla = state['use_nla']
    if 'timeline' in state:
        bpy.context.scene.frame_start, bpy.context.scene.frame_end = state['timeline']
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    for name, rows in state['basis'].items():
        if name in target.pose.bones:
            target.pose.bones[name].rotation_mode = state['modes'][name]
            target.pose.bones[name].matrix_basis = Matrix(rows)
    for name, key, value in state['properties']:
        if name in target.pose.bones:
            target.pose.bones[name][key] = value
    bpy.context.view_layer.update()
    return previous
