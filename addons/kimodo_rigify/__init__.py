"""Blender N 패널의 로컬 Kimodo 생성 및 Rigify 자동 리타게팅."""
bl_info = {'name': 'Kimodo Local → Rigify / Mixamo', 'author': 'Codex', 'version': (0, 3, 0),
           'blender': (4, 2, 0), 'location': '3D View > Sidebar > Kimodo',
           'description': '로컬 SOMA 모션 생성, Rigify / Mixamo 자동 리타게팅', 'category': 'Animation'}

import bpy
from bpy.props import StringProperty, EnumProperty, IntProperty, BoolProperty, PointerProperty
from bpy.types import AddonPreferences, PropertyGroup, Operator, Panel
from pathlib import Path
import time
import uuid
import subprocess
from . import backend, motion, retarget

JOB = None


def armature_poll(self, obj):
    return obj.type == 'ARMATURE'


def local_root(context):
    prefs = context.preferences.addons.get(__package__)
    return bpy.path.abspath(prefs.preferences.install_root if prefs else backend.DEFAULT_ROOT)


class KimodoPreferences(AddonPreferences):
    bl_idname = __package__
    install_root: StringProperty(name='로컬 설치 상위 폴더', subtype='DIR_PATH', default=backend.DEFAULT_ROOT)
    def draw(self, context):
        self.layout.prop(self, 'install_root')
        self.layout.label(text='이 폴더 아래의 Kimodo / KimodoCpp 설치를 사용합니다.')


class KimodoSettings(PropertyGroup):
    backend: EnumProperty(name='생성 엔진', items=[('CPP', 'Kimodo.cpp · SOMA 30', 'Vulkan/Q8, 8GB 설정'),
        ('OFFICIAL', '공식 Kimodo · SOMA 77', 'CPU Llama + CUDA 모션')], default='CPP')
    prompt: StringProperty(name='동작 설명', default='A person walks forward.')
    frames: IntProperty(name='프레임 (30fps)', default=90, min=60, max=150)
    steps: IntProperty(name='생성 단계', default=100, min=10, max=1000)
    seed: IntProperty(name='시드', default=42, min=0, max=2147483647)
    auto_retarget: BoolProperty(name='생성 후 자동 리타게팅', default=True)
    target: PointerProperty(name='대상 리그 (Rigify / Mixamo)', type=bpy.types.Object, poll=armature_poll)
    source: PointerProperty(name='소스 SOMA', type=bpy.types.Object, poll=armature_poll)
    root_motion: BoolProperty(name='루트 이동 포함', default=True)
    fingers: BoolProperty(name='손가락 매핑 (SOMA 77)', default=True)
    hide_source: BoolProperty(name='리타게팅 후 소스 숨기기', default=True)
    frame_start: IntProperty(name='시작 프레임', default=1, min=1, max=100000)
    append_motion: BoolProperty(name='기존 모션에 이어 붙이기', default=False,
        description='이전 Action을 보존하며 마지막 프레임 다음부터 새 모션을 추가합니다')
    status: StringProperty(default='준비', options={'SKIP_SAVE'})
    running: BoolProperty(default=False, options={'SKIP_SAVE'})
    last_log: StringProperty(name='최근 로그', subtype='FILE_PATH')
    last_result: StringProperty(name='최근 결과', subtype='FILE_PATH')


def resolved_target(context):
    settings = context.scene.kimodo
    target = settings.target or context.view_layer.objects.active
    retarget.validate_target(target)
    settings.target = target
    return target


def finish_import(context, source):
    settings = context.scene.kimodo
    settings.source = source
    if settings.auto_retarget:
        target = resolved_target(context)
        action, pairs = retarget.bake(source, target, root_motion=settings.root_motion,
                                      fingers=settings.fingers, append=settings.append_motion)
        if settings.hide_source:
            source.hide_set(True)
            source.hide_render = True
        motion.select_only(target)
        settings.status = f'완료 · {int(action.frame_range[0])}~{int(action.frame_range[1])}프레임 · {len(pairs)}개 컨트롤 · {target.name}'
    else:
        settings.status = '모션 가져오기 완료'


class KIMODO_OT_check(Operator):
    bl_idname = 'kimodo.check_environment'
    bl_label = '설치 확인'
    def execute(self, context):
        try:
            backend.validate(local_root(context), context.scene.kimodo.backend)
            context.scene.kimodo.status = '로컬 실행 파일과 모델 확인 완료'
            self.report({'INFO'}, context.scene.kimodo.status)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class KIMODO_OT_generate(Operator):
    bl_idname = 'kimodo.generate'
    bl_label = '모션 생성'
    bl_description = '외부 Kimodo 프로세스로 생성 후 Blender에 가져옵니다'
    def execute(self, context):
        global JOB
        if JOB is not None:
            self.report({'ERROR'}, '진행 중인 생성 작업을 먼저 완료하거나 취소하세요.')
            return {'CANCELLED'}
        settings = context.scene.kimodo
        prompt = settings.prompt.strip()
        if not prompt or len(prompt) > 2000:
            self.report({'ERROR'}, '동작 설명은 1~2000자 영어 문장으로 입력하세요.')
            return {'CANCELLED'}
        try:
            if settings.auto_retarget:
                target = resolved_target(context)
                if settings.append_motion:
                    retarget.validate_append(target, settings.frame_start)
            # 작업 중 패널 설정 변경은 결과에 영향을 주지 않는다.
            self.scene = context.scene
            self.engine, self.frame_start = settings.backend, settings.frame_start
            self.job_options = {k: getattr(settings, k) for k in
                ('auto_retarget', 'target', 'root_motion', 'fingers', 'hide_source', 'append_motion')}
            folder = Path(local_root(context)) / 'KimodoBlender/outputs' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
            self.process, self.log, self.result = backend.start_job(local_root(context), self.engine,
                prompt, settings.frames, settings.steps, settings.seed, folder)
            self.started = time.monotonic()
            self.cancelled = False
            settings.last_log = str(folder / 'generation.log')
            settings.last_result = str(self.result)
            settings.running = True
            settings.status = '모델 로딩 / 생성 중…'
            JOB = self
            self.timer = context.window_manager.event_timer_add(0.5, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def close_job(self, context):
        global JOB
        if getattr(self, 'closed', False):
            return
        self.closed = True
        context.window_manager.event_timer_remove(self.timer)
        self.log.close()
        self.scene.kimodo.running = False
        JOB = None

    def modal(self, context, event):
        if event.type == 'ESC':
            self.stop()
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        code = self.process.poll()
        settings = self.scene.kimodo
        if code is None:
            settings.status = f'생성 중 · {int(time.monotonic() - self.started)}초 경과'
            for area in context.screen.areas:
                area.tag_redraw()
            return {'RUNNING_MODAL'}
        self.close_job(context)
        if self.cancelled:
            settings.status = '생성 취소됨 · 기존 리그 보존'
            return {'CANCELLED'}
        if code != 0:
            settings.status = f'생성 실패 (종료 코드 {code}) · 로그 확인'
            self.report({'ERROR'}, settings.status)
            return {'CANCELLED'}
        if context.scene is not self.scene:
            settings.status = '생성 완료 · 원래 Scene에서 최근 결과를 가져오세요.'
            return {'FINISHED'}
        try:
            for key, value in self.job_options.items():
                setattr(settings, key, value)
            source = motion.import_bvh(self.result, self.frame_start) if self.engine == 'OFFICIAL' else motion.import_raw(self.result, self.frame_start)
            finish_import(context, source)
            self.report({'INFO'}, settings.status)
            return {'FINISHED'}
        except Exception as exc:
            settings.status = f'가져오기/베이크 실패: {exc}'
            self.report({'ERROR'}, settings.status)
            return {'CANCELLED'}

    def stop(self):
        if self.process.poll() is None:
            self.cancelled = True
            if backend.os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                self.process.terminate()

    def cancel(self, context):
        self.stop()
        self.close_job(context)


class KIMODO_OT_cancel(Operator):
    bl_idname = 'kimodo.cancel_generation'
    bl_label = '생성 취소'
    def execute(self, context):
        if JOB:
            JOB.stop()
        return {'FINISHED'}


class KIMODO_OT_import(Operator):
    bl_idname = 'kimodo.import_motion'
    bl_label = '기존 BVH / GLB 가져오기'
    bl_options = {'REGISTER', 'UNDO'}
    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.bvh;*.glb', options={'HIDDEN'})
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    def execute(self, context):
        try:
            if context.scene.kimodo.auto_retarget:
                target = resolved_target(context)
                if context.scene.kimodo.append_motion:
                    retarget.validate_append(target, context.scene.kimodo.frame_start)
            if Path(self.filepath).suffix.lower() == '.bvh':
                source = motion.import_bvh(self.filepath, context.scene.kimodo.frame_start)
            elif Path(self.filepath).suffix.lower() == '.glb':
                source = motion.import_glb(self.filepath, context.scene.kimodo.frame_start)
            else:
                raise ValueError('SOMA BVH 또는 Kimodo.cpp SOMA GLB를 선택하세요.')
            finish_import(context, source)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class KIMODO_OT_retarget(Operator):
    bl_idname = 'kimodo.retarget'
    bl_label = '자동 리타게팅 / 베이크'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            settings = context.scene.kimodo
            if not settings.source:
                raise ValueError('먼저 모션을 생성하거나 소스 SOMA를 지정하세요.')
            target = resolved_target(context)
            action, pairs = retarget.bake(settings.source, target, root_motion=settings.root_motion,
                                          fingers=settings.fingers, append=settings.append_motion)
            if settings.hide_source:
                settings.source.hide_set(True)
            motion.select_only(target)
            settings.status = f'완료 · {int(action.frame_range[0])}~{int(action.frame_range[1])}프레임 · {len(pairs)}개 컨트롤 · {target.name}'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class KIMODO_OT_log(Operator):
    bl_idname = 'kimodo.open_log'
    bl_label = '생성 로그 열기'
    def execute(self, context):
        path = context.scene.kimodo.last_log
        if path and Path(path).exists():
            bpy.ops.wm.path_open(filepath=path)
            return {'FINISHED'}
        self.report({'INFO'}, '아직 생성 로그가 없습니다.')
        return {'CANCELLED'}


class KIMODO_OT_next(Operator):
    bl_idname = 'kimodo.next_segment'
    bl_label = '다음 구간 (기존 모션 뒤에 추가)'
    def execute(self, context):
        try:
            target = resolved_target(context)
            action = target.animation_data.action if target.animation_data else None
            if action is None:
                raise ValueError('대상 리그에 먼저 모션을 적용하세요.')
            start = int(action.frame_range[1]) + 1
            retarget.validate_append(target, start)
            context.scene.kimodo.frame_start = start
            context.scene.kimodo.append_motion = True
            context.scene.kimodo.status = f'다음 모션: {start}프레임부터 · 대상 {target.name}'
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class KIMODO_OT_restore(Operator):
    bl_idname = 'kimodo.restore_previous'
    bl_label = '이전 Action / 리그 상태 복원'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        try:
            previous = retarget.restore_previous(resolved_target(context))
            context.scene.kimodo.status = '이전 상태 복원 완료 · ' + (previous.name if previous else 'Action 없음')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class KIMODO_PT_panel(Panel):
    bl_label = 'Kimodo Local → Rigify / Mixamo'
    bl_idname = 'KIMODO_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Kimodo'
    def draw(self, context):
        layout, settings = self.layout, context.scene.kimodo
        box = layout.column()
        box.enabled = not settings.running
        box.prop(settings, 'backend')
        box.operator('kimodo.check_environment', icon='CHECKMARK')
        box.prop(settings, 'prompt')
        row = box.row(align=True)
        row.prop(settings, 'frames')
        row.prop(settings, 'steps')
        box.prop(settings, 'seed')
        box.prop(settings, 'frame_start')
        box.prop(settings, 'append_motion')
        box.operator('kimodo.next_segment', icon='NEXT_KEYFRAME')
        box.prop(settings, 'auto_retarget')
        box.prop(settings, 'target')
        candidate = settings.target or context.view_layer.objects.active
        if candidate and candidate.type == 'ARMATURE':
            try:
                box.label(text='감지된 리그: ' + retarget.target_kind(candidate))
            except ValueError:
                box.label(text='지원하는 Rigify / Mixamo 리그를 선택하세요.', icon='INFO')
        box.prop(settings, 'root_motion')
        box.prop(settings, 'fingers')
        box.prop(settings, 'hide_source')
        box.operator('kimodo.generate', icon='PLAY')
        if settings.running:
            layout.operator('kimodo.cancel_generation', icon='CANCEL')
        layout.label(text=settings.status[:85])
        box = layout.column()
        box.enabled = not settings.running
        box.separator()
        box.operator('kimodo.import_motion', icon='IMPORT')
        box.prop(settings, 'source')
        box.operator('kimodo.retarget', icon='ARMATURE_DATA')
        box.operator('kimodo.restore_previous', icon='LOOP_BACK')
        layout.operator('kimodo.open_log', icon='TEXT')


CLASSES = (KimodoPreferences, KimodoSettings, KIMODO_OT_check, KIMODO_OT_generate,
           KIMODO_OT_cancel, KIMODO_OT_import, KIMODO_OT_retarget, KIMODO_OT_log, KIMODO_OT_next, KIMODO_OT_restore, KIMODO_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.kimodo = PointerProperty(type=KimodoSettings)


def unregister():
    if JOB:
        JOB.stop()
        JOB.close_job(bpy.context)
    if hasattr(bpy.types.Scene, 'kimodo'):
        del bpy.types.Scene.kimodo
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
