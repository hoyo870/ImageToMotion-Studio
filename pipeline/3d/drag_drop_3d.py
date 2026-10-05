"""Windows drag-and-drop entry point. Validate every input before any generation."""
import argparse
import contextlib
import hashlib
import http.client
import socket
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))  # Embedded Python does not add the script directory.
BASE = 'http://127.0.0.1:8189'
VIEWS = ('front', 'back', 'left', 'right')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}

def validate_inputs(arguments):
    """No server calls or file writes occur here."""
    from PIL import Image
    if len(arguments) not in (1, 4):
        raise ValueError('이미지 1장 또는 front/back/left/right 4장을 함께 드래그하세요. 2·3장 또는 5장 이상은 실행하지 않습니다.')
    images = {}
    seen = set()
    for argument in arguments:
        path = Path(argument).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError(f'지원하는 이미지 파일이 아닙니다: {path.name}')
        if os.path.normcase(str(path)) in seen:
            raise ValueError(f'중복 파일입니다: {path.name}')
        seen.add(os.path.normcase(str(path)))
        view = 'front' if len(arguments) == 1 else path.stem.casefold()
        if view not in VIEWS:
            raise ValueError(f'멀티뷰 파일명 오류: {path.name}. 확장자를 제외한 이름은 front, back, left, right 중 하나여야 합니다.')
        if view in images:
            raise ValueError(f'중복 방향입니다: {view}. 각 방향은 정확히 1장이어야 합니다.')
        with Image.open(path) as image:
            if getattr(image, 'is_animated', False):
                raise ValueError(f'움직이는 이미지 대신 정지 이미지를 사용하세요: {path.name}')
            image.verify()
        with Image.open(path) as image:
            image.load()  # Check decoded pixels as well as headers.
            if min(image.size) < 32:
                raise ValueError(f'이미지가 너무 작습니다: {path.name} ({image.size})')
        images[view] = path
    if len(arguments) == 4 and set(images) != set(VIEWS):
        raise ValueError('front, back, left, right 4방향이 모두 필요합니다.')
    if len(arguments) == 4 and len({os.path.normcase(str(path.parent)) for path in images.values()}) != 1:
        raise ValueError('멀티뷰 front/back/left/right 이미지는 모두 같은 폴더에 있어야 합니다. 생성하지 않습니다.')
    return ('single' if len(arguments) == 1 else 'multi'), images

def request(path, data=None, timeout=8):
    encoded = None if data is None else json.dumps(data).encode('utf-8')
    req = urllib.request.Request(BASE + path, encoded, {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'ComfyUI HTTP {error.code}: {error.read().decode("utf-8", errors="replace")}') from error

def preflight_models():
    models = ROOT / 'ComfyUI/models'
    repo = models / 'visualbruno/TRELLIS.2-4B-FP8'
    config = repo / 'pipeline_fp8.json'
    if not config.is_file():
        raise FileNotFoundError(f'설치된 FP8 모델 설정이 없습니다: {config}')
    args = json.loads(config.read_text(encoding='utf-8'))['args']
    required = [models/'background_removal/birefnet.safetensors']
    required += [models/'facebook/dinov3-vitl16-pretrain-lvd1689m'/name for name in ('model.safetensors','config.json','preprocessor_config.json')]
    for key in ('sparse_structure_flow_model','sparse_structure_decoder','shape_slat_flow_model_512','shape_slat_flow_model_1024','shape_slat_decoder','tex_slat_flow_model_1024','tex_slat_decoder'):
        name = args['models'][key]
        stem = Path(name) if Path(name).is_absolute() else (models/name if name.startswith('microsoft/') else repo/name)
        required += [Path(str(stem)+extension) for extension in ('.json','.safetensors')]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError('필요한 로컬 모델 파일이 없습니다. 자동 다운로드나 생성은 하지 않습니다:\n'+'\n'.join(missing))

@contextlib.contextmanager
def exclusive_run():
    import msvcrt
    with (ROOT/'drag_drop_3d.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('다른 드래그 생성이 실행 중입니다. 완료 후 다시 실행하세요.') from error
        try:
            yield
        finally:
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

def ensure_server(lease=None):
    try:
        info = request('/object_info', timeout=3)
    except urllib.error.URLError:
        # A detached server can inherit pipe handles even after PowerShell exits.
        # Redirect to a real file so run() waits only for PowerShell, not pipe EOF.
        startup_log = ROOT/'logs/drag_drop_startup.log'
        startup_log.parent.mkdir(exist_ok=True)
        with startup_log.open('wb') as log:
            process = subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'start_3d.ps1')], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode:
            raise RuntimeError(f'3D ComfyUI 시작 실패. 로그 확인: {startup_log}')
        if lease is not None:
            match = re.search(r"3D ComfyUI PID: (\d+)",startup_log.read_text(encoding="utf-8",errors="replace"))
            if match: lease["pid"] = int(match.group(1))
        deadline = time.monotonic()+180
        while True:
            if lease and lease.get('pid') and not server_alive(lease):
                raise RuntimeError(f'3D ComfyUI 초기화 중 종료되었습니다. 로그 확인: {ROOT / "logs/server.stderr.log"}')
            try:
                info = request('/object_info', timeout=3); break
            except urllib.error.URLError:
                if time.monotonic() > deadline:
                    raise RuntimeError(f'3D ComfyUI 시작 시간 초과. 로그 확인: {ROOT / "logs/server.stderr.log"}')
                time.sleep(2)
    needed = ('Trellis2LoadModel','Trellis2MeshWithVoxelGenerator','Trellis2MeshWithVoxelMultiViewGenerator','Trellis2PostProcessAndUnWrapAndRasterizer','Trellis2ExportMesh','RemoveBackground','ImageCropToMask','LocalMappingCropRGBA','LocalSourceProjection2048')
    missing = [name for name in needed if name not in info]
    if missing:
        raise RuntimeError('8189 서버에 필요한 3D 노드가 없습니다: '+', '.join(missing))
    identity = request('/image-to-motion/identity')
    actual_input = Path(identity['input_directory']).resolve()
    expected_input = (ROOT/'ComfyUI/input').resolve()
    if os.path.normcase(str(actual_input)) != os.path.normcase(str(expected_input)):
        raise RuntimeError('8189 서버는 다른 설치 폴더에서 실행 중입니다. 해당 서버를 직접 종료하거나 이 설치의 ComfyUI를 실행하세요.')
    queue = request('/queue')
    if queue['queue_running'] or queue['queue_pending']:
        raise RuntimeError('3D ComfyUI가 다른 작업을 처리 중입니다. 해당 작업 완료 후 다시 드래그하세요.')
    return info

def build_graph(mode, filenames, prefix):
    graph = json.loads((ROOT/'drag_drop_templates'/f'{mode}_API.json').read_text(encoding='utf-8'))['prompt']
    for index, view in enumerate(VIEWS if mode == 'multi' else ('front',)):
        node_id = 10 + index*4
        graph[str(node_id)]['inputs']['image'] = filenames[view]
        mapping_id = str(60+index*2)
        graph[mapping_id] = {'class_type':'LoadImage','inputs':{'image':filenames[view].replace('_1024.png','_2048.png')}}
        graph[str(61+index*2)] = {'class_type':'LocalMappingCropRGBA','inputs':{'image':[mapping_id,0],'mask':[str(node_id+1),0]}}
        graph[str(node_id+3)]['inputs']['filename_prefix'] = prefix+'/'+view+'_input'
    graph['50'] = {'class_type':'LocalSourceProjection2048','inputs':{'trimesh':['40',0],**{view+'_image':[str(61+i*2),0] for i,view in enumerate(VIEWS if mode=='multi' else ('front',))}}}
    for node,slot in (('41',0),('42',1),('43',2)):
        graph[node]['inputs']['trimesh' if node=='41' else 'images']=['50',slot]
    graph['41']['inputs']['filename_prefix'] = prefix+'/model_textured'
    graph['42']['inputs']['filename_prefix'] = prefix+'/base_color'
    graph['43']['inputs']['filename_prefix'] = prefix+'/metallic_roughness'
    return graph

def check_graph(graph, info):
    for key, node in graph.items():
        schema = info[node['class_type']]['input']
        missing = set(schema.get('required',{}))-set(node['inputs'])
        if missing:
            raise RuntimeError(f'워크플로 필수 입력 누락: {key} {sorted(missing)}')
        allowed=set(schema.get('required',{}))|set(schema.get('optional',{}))|set(schema.get('hidden',{}))
        extra=set(node['inputs'])-allowed
        if extra: raise RuntimeError(f'워크플로 알 수 없는 입력: {key} {sorted(extra)}')
        for value in node['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):
                if value[0] not in graph or value[1] >= len(info[graph[value[0]]['class_type']]['output']):
                    raise RuntimeError(f'워크플로 연결 오류: {key} {value}')

def cancel_owned_prompt(prompt_id):
    if not prompt_id:
        return
    try:
        queue = request('/queue')
        if any(entry[1]==prompt_id for entry in queue['queue_pending']):
            request('/queue', {'delete':[prompt_id]})
        if any(entry[1]==prompt_id for entry in queue['queue_running']):
            request('/interrupt', {})
    except Exception:
        pass

def export_result(history, directory, texture_size=2048):
    from PIL import Image
    import numpy as np
    import trimesh
    # Only retrieve artifacts produced by this prompt, never older directory files.
    exported = {}
    for node_id, destination, extension in (('41','model_textured.glb','.glb'),('42',f'base_color_{texture_size}.png','.png'),('43',f'metallic_roughness_{texture_size}.png','.png')):
        items = history['outputs'].get(node_id,{})
        artifacts = [item for values in items.values() if isinstance(values,list) for item in values if isinstance(item,dict) and 'filename' in item]
        artifact = next((item for item in artifacts if item['filename'].lower().endswith(extension)),None)
        if artifact is None:
            raise RuntimeError(f'생성 결과에서 {destination} 파일을 찾지 못했습니다: {items}')
        if artifact.get('type','output') != 'output':
            raise RuntimeError(f'예상하지 않은 결과 파일 종류: {artifact}')
        source = (ROOT/'ComfyUI/output'/artifact.get('subfolder','')/artifact['filename']).resolve()
        if not source.is_relative_to((ROOT/'ComfyUI/output').resolve()):
            raise RuntimeError('결과 경로가 ComfyUI 출력 폴더 밖을 가리킵니다.')
        shutil.copy2(source,directory/destination); exported[destination]=str(source)
    for name in (f'base_color_{texture_size}.png',f'metallic_roughness_{texture_size}.png'):
        with Image.open(directory/name) as image:
            image.load()
            if image.size != (texture_size,texture_size):
                raise RuntimeError(f'텍스처 크기가 {texture_size}가 아닙니다: {name} {image.size}')
    scene = trimesh.load(directory/'model_textured.glb', force='scene', process=False)
    audits=[]
    for mesh in scene.geometry.values():
        uv = getattr(mesh.visual,'uv',None)
        material = getattr(mesh.visual,'material',None)
        if uv is None or not np.isfinite(uv).all() or len(uv)!=len(mesh.vertices):
            raise RuntimeError('GLB UV 좌표가 누락되거나 잘못되었습니다.')
        if material is None or material.baseColorTexture is None or material.metallicRoughnessTexture is None:
            raise RuntimeError('GLB에 텍스처가 내장되지 않았습니다.')
        topology = trimesh.Trimesh(mesh.vertices,mesh.faces,process=False)
        topology.merge_vertices()
        if material.baseColorTexture.size != (texture_size,texture_size) or material.metallicRoughnessTexture.size != (texture_size,texture_size):
            raise RuntimeError('GLB 내장 텍스처 크기가 잘못되었습니다.')
        audits.append(dict(triangles=len(mesh.faces),uv_vertices=len(uv),watertight=bool(topology.is_watertight),winding_consistent=bool(topology.is_winding_consistent)))
    if not audits:
        raise RuntimeError('GLB에 메시가 없습니다.')
    return dict(files=exported,meshes=audits,texture_size=[texture_size,texture_size])


def prepare_inputs(source, target):
    from PIL import Image, ImageOps
    with Image.open(source) as original:
        original=ImageOps.exif_transpose(original).convert('RGB'); size=original.size
        outputs={}
        for resolution in (1024,2048):
            image=ImageOps.pad(original,(resolution,resolution),method=Image.Resampling.LANCZOS,color=(0,0,0))
            destination=target.with_name(target.name.replace('_1024.png',f'_{resolution}.png'))
            image.save(destination)
            outputs[str(resolution)]=str(destination)
    hashes={}
    for key,name in outputs.items():
        with Path(name).open('rb') as handle: hashes[key]=hashlib.file_digest(handle,'sha256').hexdigest()
    with Path(source).open('rb') as handle: source_hash=hashlib.file_digest(handle,'sha256').hexdigest()
    return dict(source_size=list(size),source_sha256=source_hash,method='Lanczos, aspect-preserving padding; not AI detail synthesis',outputs=outputs,sha256=hashes)

def close_owned_server(lease, directory=None, prompt_id=None):
    pid=lease.get('pid')
    if not pid:
        if directory: (directory/'server_lifecycle.json').write_text(json.dumps(dict(started_by_batch=False,shutdown_requested=False,reason='Pre-existing manual server is preserved'),indent=2),encoding='utf-8')
        return
    try:
        try:
            queue=request('/queue',timeout=30)
        except urllib.error.URLError:
            queue={'queue_running':[],'queue_pending':[]}
        foreign=[entry for entry in queue['queue_running']+queue['queue_pending'] if entry[1]!=prompt_id]
        if foreign:
            raise RuntimeError('Owned server retained because another job is queued.')
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
            '-File',str(ROOT/'close_owned_server.ps1'),str(pid),str(ROOT/'python_embeded/python.exe')],
            capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise RuntimeError(f"Shutdown exit {result.returncode}: {result.stdout} {result.stderr}")
        if directory: (directory/'server_lifecycle.json').write_text(json.dumps(dict(started_by_batch=True,pid=pid,shutdown_requested=True),indent=2),encoding='utf-8')
    except Exception as error:
        print('오류: 자동 종료 확인 필요: '+str(error),file=sys.stderr)


NETWORK_ERRORS=(urllib.error.URLError,TimeoutError,ConnectionError,http.client.IncompleteRead)

def server_alive(lease):
    pid=lease.get('pid')
    if pid and os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if handle:
            try:
                code=wintypes.DWORD()
                if kernel.GetExitCodeProcess(handle,ctypes.byref(code)):return code.value==259
            finally:kernel.CloseHandle(handle)
        elif ctypes.get_last_error()==87:return False
    try:
        endpoint=urllib.parse.urlsplit(BASE)
        with socket.create_connection((endpoint.hostname,endpoint.port or 80),timeout=2):return True
    except OSError:return False

def wait_for_history(prompt_id,lease,directory):
    unavailable=0;delays=0
    while True:
        try:
            history=request('/history/'+prompt_id,timeout=30)
            unavailable=0
        except NETWORK_ERRORS as error:
            alive=server_alive(lease)
            unavailable=0 if alive else unavailable+1
            delays+=1
            with (directory/'client_status.jsonl').open('a',encoding='utf-8') as log:
                log.write(json.dumps(dict(time=datetime.now(timezone(timedelta(hours=9))).isoformat(),event='status_request_retry',error=type(error).__name__,message=str(error),server_alive=alive),ensure_ascii=False)+'\n')
            if delays==1:print('서버 상태 응답이 지연되고 있습니다. 프로세스가 실행 중이면 생성을 취소하지 않고 계속 기다립니다.',flush=True)
            if unavailable>=3:raise RuntimeError(f'ComfyUI 서버가 종료되어 연결할 수 없습니다. 작업 ID: {prompt_id}') from error
            time.sleep(5);continue
        if prompt_id in history:
            result=history[prompt_id]
            (directory/'history.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            if result['status']['status_str']!='success':
                errors=[item for name,item in result['status']['messages'] if name=='execution_error']
                message=errors[-1].get('exception_message','생성 실패') if errors else str(result['status'])
                raise RuntimeError(message)
            return result
        time.sleep(5)

def run_mesh_cleanup(directory):
    # Cleanup runs on a separate copy; ComfyUI's textured original is retained.
    cleanup = directory/'cleanup'
    blender = ROOT/'Blender/blender-4.5.9-windows-x64/blender.exe'
    if not blender.is_file():
        raise FileNotFoundError(f'자동 메시 정리용 Blender가 없습니다: {blender}')
    with (directory/'cleanup_blender.log').open('wb') as log:
        completed = subprocess.run([str(blender),'--background','--factory-startup',
            '--python-exit-code','1','--python',str(ROOT/'cleanup_mesh.py'),
            '--','--input',str(directory/'model_textured.glb'),'--output',str(cleanup)],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
    if completed.returncode or not (cleanup/'cleanup_report.json').is_file():
        raise RuntimeError(f'3D 생성·매핑은 완료했지만 메시 정리에 실패했습니다. 원본 보존됨. 로그: {directory / "cleanup_blender.log"}')
    return json.loads((cleanup/'cleanup_report.json').read_text(encoding='utf-8'))

def copy_final_to_inputs(directory, mode, images, report):
    """Publish validated final only; exclusive create prevents overwriting/races."""
    if report.get('status') != 'completed_review_required' or report.get('mode') != mode:
        raise ValueError('검증 완료된 최종 결과만 입력 폴더로 복사할 수 있습니다.')
    minimum, maximum = (1000,1500) if mode == 'single' else (2000,3000)
    if not minimum <= report['geometry']['vertices'] <= maximum:
        raise ValueError('최종 버텍스 검사 미통과: 복사하지 않습니다.')
    paths = list(images.values())
    parents = {os.path.normcase(str(path.parent.resolve())) for path in paths}
    if not paths or len(parents) != 1:
        raise ValueError('입력 이미지 폴더가 일치하지 않아 최종 결과를 복사하지 않습니다.')
    folder = paths[0].parent.resolve()
    stem = paths[0].stem if mode == 'single' else folder.name
    source = directory/'retopology/model_final.glb'
    size = source.stat().st_size
    with source.open('rb') as handle:
        header = handle.read(12)
    if header[:4] != b'glTF' or len(header) != 12 or int.from_bytes(header[8:12],'little') != size:
        raise ValueError('최종 GLB 파일이 손상되었거나 불완전합니다. 복사하지 않습니다.')
    for index in range(10000):
        name = stem+'.glb' if index == 0 else f'{stem}_{index:03d}.glb'
        destination = folder/name
        try:
            output = destination.open('xb')
        except FileExistsError:
            continue
        try:
            with output, source.open('rb') as handle:
                shutil.copyfileobj(handle,output)
            with source.open('rb') as handle:
                expected = hashlib.file_digest(handle,'sha256').hexdigest()
            with destination.open('rb') as handle:
                actual = hashlib.file_digest(handle,'sha256').hexdigest()
            if expected != actual:
                raise RuntimeError('복사된 GLB 파일의 해시가 일치하지 않습니다.')
        except BaseException:
            # Only this invocation's newly created file; never an existing result.
            destination.unlink(missing_ok=True)
            raise
        publication = dict(source=str(source),copied_to=str(destination),sha256=actual,
                           naming='image stem' if mode == 'single' else 'input folder name',
                           overwrite=False)
        (directory/'input_folder_copy.json').write_text(json.dumps(publication,ensure_ascii=False,indent=2),encoding='utf-8')
        return publication
    raise RuntimeError('같은 이름의 GLB가 너무 많아 새 파일 이름을 만들 수 없습니다.')


def main():
    parser = argparse.ArgumentParser(description='이미지 1장 또는 front/back/left/right 4장 → 3D + 텍스처 GLB')
    parser.add_argument('images',nargs='*')
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--postprocess-only',type=Path)
    parser.add_argument('--postprocess-mode',choices=['single','multi'])
    args = parser.parse_args()
    directory = None; prompt_id = None; lease = {}
    try:
        from retopo_pipeline import run_retopology, preflight_tools
        if args.postprocess_only:
            if not args.postprocess_mode:
                raise ValueError('--postprocess-only에는 --postprocess-mode single 또는 multi가 필요합니다.')
            source=(args.postprocess_only/'model_textured.glb').resolve(strict=True)
            preflight_tools()
            with exclusive_run():
                stamp=datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
                directory=ROOT/'results/postprocess'/f'{stamp}_{args.postprocess_mode}_{uuid.uuid4().hex[:8]}'
                directory.mkdir(parents=True)
                shutil.copy2(source,directory/'model_textured.glb')
                cleanup=run_mesh_cleanup(directory)
                report=run_retopology(directory,args.postprocess_mode)
                (directory/'validation.json').write_text(json.dumps(dict(cleanup=cleanup,retopology=report),indent=2),encoding='utf-8')
                print(f'완료 (보수 검토 필요): {directory / "retopology/model_final.blend"}',flush=True)
                if not args.no_open: os.startfile(directory)
                return 0
        mode, images = validate_inputs(args.images)
        if args.validate_only or os.environ.get('COMFY3D_VALIDATE_ONLY')=='1':
            print(json.dumps(dict(valid=True,mode=mode,views=list(images)),ensure_ascii=False)); return 0
        preflight_models()
        preflight_tools()
        with exclusive_run():
            info = ensure_server(lease)
            # Client time zone is Korea, independent of process working directory.
            stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
            run_id = f'{stamp}_{mode}_{uuid.uuid4().hex[:8]}'
            prefix = 'drag_drop/'+run_id
            filenames = {view:prefix+'/'+view+'_1024.png' for view,path in images.items()}
            graph = build_graph(mode,filenames,prefix); check_graph(graph,info)
            if args.dry_run or os.environ.get('COMFY3D_DRY_RUN')=='1':
                print(json.dumps(dict(valid=True,mode=mode,graph_checked=True,nodes=len(graph),queued=False),ensure_ascii=False)); return 0
            directory = ROOT/'results/drag_drop'/run_id
            directory.mkdir(parents=True)
            input_dir = ROOT/'ComfyUI/input'/prefix; input_dir.mkdir(parents=True)
            manifest=[]
            for view,path in images.items():
                target = ROOT/'ComfyUI/input'/filenames[view]
                preprocessing = prepare_inputs(path,target)
                with target.open('rb') as handle:
                    sha = hashlib.file_digest(handle,'sha256').hexdigest()
                manifest.append(dict(view=view,source=str(path),copied_input=str(target),sha256=sha,preprocessing=preprocessing))
            (directory/'input_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            (directory/'workflow_API.json').write_text(json.dumps({'prompt':graph},indent=2),encoding='utf-8')
            submitted = request('/prompt', {'prompt':graph,'client_id':'drag-drop-'+run_id})
            prompt_id = submitted['prompt_id']
            (directory/'submission.json').write_text(json.dumps(submitted,indent=2),encoding='utf-8')
            print(f'생성 시작: {"싱글뷰" if mode=="single" else "멀티뷰 4방향"} / 형상 1024 / 투영 텍스처 2048. 입력 복잡도에 따라 수십 분 걸릴 수 있습니다.\n결과 폴더: {directory}',flush=True)
            history = wait_for_history(prompt_id,lease,directory)
            audit = export_result(history,directory)
            audit['cleanup'] = run_mesh_cleanup(directory)
            audit['retopology'] = run_retopology(directory,mode)
            audit.update(mode=mode,prompt_id=prompt_id,status='success')
            messages = history['status']['messages']
            audit['execution_seconds'] = (next(item['timestamp'] for name,item in messages if name=='execution_success')-next(item['timestamp'] for name,item in messages if name=='execution_start'))/1000
            audit['input_folder_copy'] = copy_final_to_inputs(directory,mode,images,audit['retopology'])
            (directory/'validation.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
            note = '수밀 검사 통과' if all(mesh['watertight'] for mesh in audit['meshes']) else '수밀 검사 미통과: 메시 연결·구멍은 추가 정리가 필요합니다.'
            (directory/'RESULT.txt').write_text(f'3D 1024 생성 및 원본 투영 2048 텍스처 매핑 완료\n방식: {mode}\n실행 시간: {audit["execution_seconds"]:.1f}초\n{note}\n\nmodel_textured.glb: UV와 텍스처 내장\nbase_color_2048.png: 색상 맵\nmetallic_roughness_2048.png: Metallic/Roughness 맵\nworkflow_API.json: 재현용 설정\n',encoding='utf-8')
            with (directory/'RESULT.txt').open('a',encoding='utf-8') as result_note:
                result_note.write('\n자동 메시 정리 완료: cleanup/model_cleaned.blend 및 model_cleaned.glb\n정리 전후 결함 기록: cleanup/cleanup_report.json\n큰 구멍·교차 면 등은 추가 보수 필요: cleanup/REVIEW.txt\n')
                final=audit['retopology']
                result_note.write(f'\n리토폴로지·2048 재베이킹 완료 (보수 검토 필요)\n최종: retopology/model_final.blend, model_final.glb\nBlender 정점: {final["geometry"]["vertices"]}\nGLB 정점: {final["exported_glb_vertices"]}\n검사: retopology/retopo_report.json\n')
                result_note.write(f'\n입력 폴더에 복사: {audit["input_folder_copy"]["copied_to"]}\n')
            print(f'완료 (보수 검토 필요): {audit["input_folder_copy"]["copied_to"]}\n{note}',flush=True)
            if not args.no_open and os.environ.get('COMFY3D_NO_OPEN')!='1':
                try:
                    os.startfile(directory)
                except OSError:
                    print(f'결과 폴더를 직접 열어주세요: {directory}',flush=True)
            return 0
    except (Exception,KeyboardInterrupt) as error:
        cancel_owned_prompt(prompt_id)
        message = '사용자가 취소했습니다.' if isinstance(error,KeyboardInterrupt) else str(error)
        if directory:
            (directory/'ERROR.txt').write_text(message+'\n작업 ID: '+str(prompt_id),encoding='utf-8')
        print('오류: '+message,file=sys.stderr,flush=True)
        return 1
    finally:
        close_owned_server(lease,directory,prompt_id)

if __name__=='__main__':
    raise SystemExit(main())
