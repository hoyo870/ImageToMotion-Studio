"""Windows installer: portable runtimes, pinned downloads, safe reuse and repair."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.state'
RUNTIME = ROOT / 'runtime'
STATE.mkdir(exist_ok=True)
LOG = STATE / 'setup.log'
MANIFEST = json.loads((ROOT / 'manifests/software.json').read_text())
MODELS = json.loads((ROOT / 'manifests/models.json').read_text())


def say(message):
    print(message, flush=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(message + '\n')


def run(argv, cwd=None, env=None, timeout=1800):
    with LOG.open('a', encoding='utf-8') as log:
        p = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                           stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:
        raise RuntimeError(f'{Path(str(argv[0])).name} failed ({p.returncode}); see {LOG}')


def output(argv, timeout=120, env=None):
    return subprocess.check_output([str(a) for a in argv], timeout=timeout,
                                   env=env, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8', 'replace')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def verified(path, item):
    if not path.is_file() or path.stat().st_size != item['bytes']:
        return False
    # Cache a previously verified digest only while both size and timestamp match.
    cache = STATE / 'hashes.json'
    entries = json.loads(cache.read_text()) if cache.exists() else {}
    key = str(path.resolve())
    stamp = [path.stat().st_size, path.stat().st_mtime_ns, item['sha256']]
    if entries.get(key) == stamp:
        return True
    if sha(path) != item['sha256']:
        return False
    entries[key] = stamp
    cache.write_text(json.dumps(entries, indent=2))
    return True


def download(item, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if verified(dest, item):
        say('SKIP verified: ' + dest.name)
        return dest
    part = dest.with_name(dest.name + '.part')
    for attempt in range(3):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset >= item['bytes']:
                if offset == item['bytes'] and sha(part) == item['sha256']:
                    part.replace(dest)
                    return dest
                part.unlink()
                offset = 0
            req = urllib.request.Request(item['url'], headers={
                'User-Agent': 'ImageToMotion-Studio/0.1',
                **({'Range': f'bytes={offset}-'} if offset else {})})
            say('DOWNLOAD: ' + dest.name)
            # Windows curl also works with CDNs that reject urllib's TLS fingerprint.
            result = subprocess.run(['curl.exe', '-fL', '--retry', '3', '--connect-timeout', '30',
                                     '-C', '-', '-o', str(part), item['url']],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=7200, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(f'Download failed ({result.returncode}): {dest.name}')
            if part.stat().st_size != item['bytes'] or sha(part) != item['sha256']:
                part.unlink()
                raise RuntimeError('Download size/SHA256 mismatch: ' + dest.name)
            part.replace(dest)
            return dest
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def reuse_model(item, dest, cached):
    if dest.exists() or not cached or not verified(cached, item):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(cached, dest)
    except OSError:
        shutil.copy2(cached, dest)
    say('SKIP reuse verified model: ' + dest.name)


def extract(archive, dest, strip=False):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            bits = Path(entry.filename).parts[1:] if strip else Path(entry.filename).parts
            if not bits:
                continue
            target = (dest / Path(*bits)).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError('Unsafe archive path')
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)


def junction(dest, source):
    if dest.exists():
        if dest.resolve() != source.resolve():
            raise RuntimeError('Conflicting runtime path; preserve it and choose a new folder: ' + str(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Literal directory junctions do not need admin privileges and preserve source files.
    run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         ROOT / 'installer/junction.ps1', str(dest), str(source)])


def snapshot(key, dest, existing=None):
    item = MANIFEST[key]
    marker = dest / '.imt-version'
    if marker.exists() and marker.read_text() == item['revision']:
        return
    if existing and (existing / '.git').exists():
        head = output(['git', '-C', existing, 'rev-parse', 'HEAD']).strip()
        dirty = output(['git', '-C', existing, 'status', '--porcelain']).strip()
        if head == item['revision'] and not dirty:
            def ignored(directory, names):
                skip = shutil.ignore_patterns('.git', '__pycache__', '*.pyc')(directory, names)
                if key == 'comfyui' and Path(directory) == existing:
                    skip.update(n for n in names if n in ('models','input','output','user','custom_nodes'))
                return skip
            shutil.copytree(existing, dest, dirs_exist_ok=True, ignore=ignored)
            marker.write_text(item['revision'])
            return
    archive = download(item, STATE / (key + '.zip'))
    extract(archive, dest, strip=True)
    marker.write_text(item['revision'])


def python_check(exe):
    code = """import sys,json,torch,cumesh,o_voxel,nvdiffrast,triton,PIL,trimesh
assert sys.version_info[:2]==(3,12)
assert torch.__version__=='2.8.0+cu128' and torch.version.cuda=='12.8'
assert torch.cuda.is_available(), 'CUDA unavailable'
cap=torch.cuda.get_device_capability(0); assert 7<=cap[0]<=9, 'Unsupported GPU profile'
assert torch.cuda.get_device_properties(0).total_memory>=7.5*1024**3, '8GB VRAM required'
x=torch.ones((32,32),device='cuda'); assert (x@x)[0,0].item()==32
print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'capability':cap}))
"""
    details = json.loads(output([exe, '-c', code]).strip().splitlines()[-1])
    output([exe, '-m', 'pip', 'check'])
    return details


def install_python(three, candidate):
    py = three / 'python_embeded/python.exe'
    if py.exists():
        try:
            return py, python_check(py)
        except Exception:
            if (three / 'python_embeded').is_junction():
                raise RuntimeError('Shared Python became incompatible; use a new isolated folder')
            say('REPAIR incomplete dedicated Python environment')
            pip = download(MANIFEST['get-pip'], STATE / 'get-pip.py')
            run([py, pip])
            run([py, '-m', 'pip', 'install', '--extra-index-url', 'https://download.pytorch.org/whl/cu128',
                 '-r', ROOT / 'manifests/requirements-3d.lock'], timeout=7200)
            return py, python_check(py)
    if candidate:
        try:
            info = python_check(candidate / 'python_embeded/python.exe')
            junction(three / 'python_embeded', candidate / 'python_embeded')
            say('SKIP compatible 3D Python and dependencies')
            return py, info
        except Exception as error:
            say('Existing 3D Python not reused: ' + str(error))
    shutil.copytree(RUNTIME / 'bootstrap', three / 'python_embeded', dirs_exist_ok=True)
    headers = ROOT / 'vendor/runtime/python-3.12-include-libs.zip'
    if not verified(headers, MANIFEST['python-jit-headers']):
        raise RuntimeError('Python JIT headers hash mismatch')
    extract(headers, three / 'python_embeded')
    (three / 'python_embeded/python312._pth').write_text('python312.zip\n.\n../ComfyUI\nLib/site-packages\nimport site\n')
    pip = download(MANIFEST['get-pip'], STATE / 'get-pip.py')
    run([py, pip])
    run([py, '-m', 'pip', 'install', '--extra-index-url', 'https://download.pytorch.org/whl/cu128',
         '-r', ROOT / 'manifests/requirements-3d.lock'], timeout=7200)
    return py, python_check(py)


def ensure_jit_headers(three):
    folder = three / 'python_embeded'
    if not folder.is_junction():
        (folder / 'python312._pth').write_text('python312.zip\n.\n../ComfyUI\nLib/site-packages\nimport site\n')
    if (folder / 'include/Python.h').exists() and (folder / 'libs/python312.lib').exists():
        return
    if folder.is_junction():
        raise RuntimeError('Reused Python lacks JIT headers; use a fresh isolated installation')
    archive = ROOT / 'vendor/runtime/python-3.12-include-libs.zip'
    if not verified(archive, MANIFEST['python-jit-headers']):
        raise RuntimeError('Python JIT header archive integrity failure')
    extract(archive, folder)


def install_blender(key, candidates):
    version = MANIFEST[key]['version']
    for exe in candidates:
        if exe.is_file():
            try:
                if output([exe, '--version']).splitlines()[0].split()[1] == version:
                    say('SKIP compatible Blender ' + version)
                    return exe
            except Exception:
                pass
    dest = RUNTIME / key
    exe = dest / 'blender.exe'
    if exe.exists() and output([exe, '--version']).splitlines()[0].split()[1] == version:
        return exe
    archive = download(MANIFEST[key], STATE / (key + '.zip'))
    extract(archive, dest, strip=True)
    (dest / 'portable').mkdir(exist_ok=True)
    return exe


def setup(fresh=False):
    if os.name != 'nt':
        raise RuntimeError('This release supports Windows x64 only')
    if sys.getwindowsversion().build < 18362:
        raise RuntimeError('Windows 10 version 1903 or newer is required for Unicode CLI paths')
    gpu = output(['nvidia-smi', '--query-gpu=name,memory.total,driver_version,compute_cap', '--format=csv,noheader'])
    say('GPU: ' + gpu.strip())
    first = [v.strip() for v in gpu.splitlines()[0].split(',')]
    if len(first) != 4 or float(first[1].split()[0]) < 7680 or not 7 <= int(float(first[3])) <= 9:
        raise RuntimeError('Unsupported GPU: this release requires an 8GB NVIDIA compute 7.x/8.x/9.x GPU')
    if shutil.disk_usage(ROOT).free < 40 * 1024 ** 3:
        raise RuntimeError('At least 40GB free disk space required')
    local = ROOT / 'local_config.json'
    overrides = json.loads(local.read_text(encoding='utf-8-sig')) if local.exists() else {}
    candidate = Path(overrides.get('existing_3d', ROOT.parent / 'AI/ComfyUI_3D_1024'))
    if fresh or not (candidate / 'python_embeded/python.exe').exists():
        candidate = None
    three = RUNTIME / 'ComfyUI_3D_1024'
    three.mkdir(parents=True, exist_ok=True)
    for d in ('logs', 'results', 'ComfyUI/input', 'ComfyUI/output'):
        (three / d).mkdir(parents=True, exist_ok=True)
    py, info = install_python(three, candidate)
    ensure_jit_headers(three)
    snapshot('comfyui', three / 'ComfyUI', candidate / 'ComfyUI' if candidate else None)
    snapshot('trellis-wrapper', three / 'ComfyUI/custom_nodes/ComfyUI-Trellis2',
             candidate / 'ComfyUI/custom_nodes/ComfyUI-Trellis2' if candidate else None)
    shutil.copytree(ROOT / 'pipeline/3d', three, dirs_exist_ok=True)
    shutil.copytree(ROOT / 'addons/comfyui-local-dual-resolution',
                    three / 'ComfyUI/custom_nodes/comfyui-local-dual-resolution', dirs_exist_ok=True)
    # Reuse complete verified model directory. Do not edit shared model configs.
    if candidate and not (three / 'ComfyUI/models').exists():
        valid = True
        for item in MODELS:
            if item['component'] != '3d' or item['destination'].endswith('pipeline_fp8.json'):
                continue
            if not verified(candidate / 'ComfyUI/models' / item['destination'], item):
                valid = False
                break
        derived = candidate / 'ComfyUI/models/visualbruno/TRELLIS.2-4B-FP8/ckpts_local/shape_dec_native_fp16.safetensors'
        if valid and derived.is_file():
            junction(three / 'ComfyUI/models', candidate / 'ComfyUI/models')
            say('SKIP verified compatible 3D models')
    if not (three / 'ComfyUI/models').is_junction():
        (three / 'ComfyUI/models/microsoft/TRELLIS.2-4B').mkdir(parents=True, exist_ok=True)
        for item in MODELS:
            if item['component'] == '3d':
                path = three / 'ComfyUI/models' / item['destination']
                if path.name == 'pipeline_fp8.json':
                    path = path.with_name('pipeline_fp8.downloaded.json')
                if candidate:
                    cached = candidate / 'ComfyUI/models' / item['destination']
                    if cached.name == 'pipeline_fp8.json':
                        cached = cached.with_name('pipeline_fp8.downloaded.json')
                    reuse_model(item, path, cached)
                download(item, path)
        model = three / 'ComfyUI/models/visualbruno/TRELLIS.2-4B-FP8'
        shutil.copy2(model / 'pipeline_fp8.downloaded.json', model / 'pipeline_fp8.json')
        if not (model / 'ckpts_local/shape_dec_native_fp16.safetensors').is_file():
            run([py, three / 'prepare_shape_decoder.py'], timeout=600)
        else:
            # Recreate path-dependent config even when derived weights already exist.
            cfg = json.loads((model / 'pipeline_fp8.json').read_text())
            cfg['args']['models']['shape_slat_decoder'] = 'ckpts_local/shape_dec_native_fp16'
            cfg['args']['models']['sparse_structure_decoder'] = str((three / 'ComfyUI/models/microsoft/TRELLIS-image-large/ckpts/ss_dec_conv3d_16l8_fp16').resolve()).replace('\\', '/')
            (model / 'pipeline_fp8.json').write_text(json.dumps(cfg, indent=2))
    post_candidates = [three / 'Blender/blender-4.5.9-windows-x64/blender.exe']
    if candidate:
        post_candidates.append(candidate / 'Blender/blender-4.5.9-windows-x64/blender.exe')
    post = install_blender('blender-post', post_candidates)
    junction(three / 'Blender/blender-4.5.9-windows-x64', post.parent)
    ui_candidates = [Path(overrides['blender'])] if overrides.get('blender') else []
    ui_candidates += list(Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('Blender Foundation/Blender */blender.exe'))
    ui = install_blender('blender-ui', [] if fresh else ui_candidates)
    tools = three / 'tools/InstantMeshes'
    tools.mkdir(parents=True, exist_ok=True)
    if not verified(ROOT / 'vendor/runtime/Instant Meshes.exe', MANIFEST['instant-meshes']):
        raise RuntimeError('Bundled Instant Meshes hash mismatch')
    shutil.copy2(ROOT / 'vendor/runtime/Instant Meshes.exe', tools / 'Instant Meshes.exe')
    shutil.copy2(ROOT / 'vendor/licenses/InstantMeshes.txt', tools / 'LICENSE.txt')
    native = RUNTIME / 'KimodoCpp/source'
    cpp = Path(overrides.get('existing_cpp', ROOT.parent / 'KimodoCpp/source'))
    if native.is_junction() and not all(verified(native/name,item) for name,item in MANIFEST['kimodo-runtime']['files'].items()):
        # Remove only our managed junction, never its target or any target files.
        native.rmdir()
        say('UPDATE managed Kimodo runtime; shared original preserved')
    if not fresh and (cpp / 'build/release/kmd-generate.exe').is_file() and not native.exists():
        if all(verified(cpp / i['destination'], i) for i in MODELS if i['component'] == 'kimodo'):
            # Verify the runtime itself, not just the model files.
            expected = MANIFEST['kimodo-runtime']['files']
            if all(verified(cpp / name, item) for name, item in expected.items()):
                junction(native, cpp)
                say('SKIP verified Kimodo.cpp runtime/models')
    if not native.is_junction():
        bundle = ROOT / 'vendor/runtime/kimodo-cpp-windows-x64.zip'
        if not verified(bundle, MANIFEST['kimodo-runtime']):
            raise RuntimeError('Bundled Kimodo runtime hash mismatch')
        extract(bundle, native)
        shutil.copytree(ROOT / 'vendor/licenses', native / 'licenses', dirs_exist_ok=True)
        for item in MODELS:
            if item['component'] == 'kimodo':
                if not fresh:
                    reuse_model(item, native / item['destination'], cpp / item['destination'])
                download(item, native / item['destination'])
    profile = RUNTIME / 'blender-profile'
    addons = profile / 'scripts/addons'
    for name in ('kimodo_rigify', 'mixamo_rig'):
        shutil.copytree(ROOT / 'addons' / name, addons / name, dirs_exist_ok=True)
    for d in ('config', 'extensions'):
        (profile / d).mkdir(parents=True, exist_ok=True)
    config = dict(three=str(three), python=str(py), blender=str(ui), post_blender=str(post),
                  cpp=str(native), profile=str(profile), hardware=info)
    (STATE / 'config.json').write_text(json.dumps(config, indent=2))
    env = blender_env(config)
    run([ui, '--factory-startup', '-b', '--python-exit-code', '1', '--python',
         ROOT / 'installer/configure_blender.py', '--', RUNTIME], env=env)
    verify(config)
    say('READY: launcher.bat / generate_3d.bat / launch_blender.bat')
    return config


def blender_env(config):
    env = os.environ.copy()
    profile = Path(config['profile'])
    env.update(BLENDER_USER_CONFIG=str(profile / 'config'),
               BLENDER_USER_SCRIPTS=str(profile / 'scripts'),
               BLENDER_USER_EXTENSIONS=str(profile / 'extensions'),
               IMT_RUNTIME_ROOT=str(RUNTIME), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return env


def verify(config):
    details = python_check(Path(config['python']))
    jit_env = os.environ.copy()
    jit_env.update(TRITON_CACHE_DIR=str(STATE / 'triton-cache'), PYTHONUTF8='1')
    output([config['python'], ROOT / 'tests/cuda_probe.py'], env=jit_env, timeout=300)
    for item in MODELS:
        folder = Path(config['three']) / 'ComfyUI/models' if item['component'] == '3d' else Path(config['cpp'])
        path = folder / item['destination']
        if path.name == 'pipeline_fp8.json':
            path = path.with_name('pipeline_fp8.downloaded.json')
        if not verified(path, item):
            raise RuntimeError('Model integrity check failed: ' + str(path))
    for name, item in MANIFEST['kimodo-runtime']['files'].items():
        if not verified(Path(config['cpp']) / name, item):
            raise RuntimeError('Kimodo runtime integrity check failed: ' + name)
    # Validate missing model/tool paths through the shipped pipeline, without GPU generation.
    code = "import sys;sys.path.insert(0,sys.argv[1]);import drag_drop_3d,retopo_pipeline;drag_drop_3d.preflight_models();retopo_pipeline.preflight_tools();print('PREFLIGHT_OK')"
    output([config['python'], '-c', code, config['three']])
    run([config['blender'], '--factory-startup', '-b', '--python-exit-code', '1', '--python',
         ROOT / 'tests/blender_smoke.py', '--', ROOT], env=blender_env(config), timeout=300)
    (STATE / 'verification.json').write_text(json.dumps(dict(status='passed', hardware=details,
        checks=['Python 3.12', 'pip check', 'CUDA matmul', 'Triton JIT compile', 'native imports', 'models/runtime SHA256', 'models/tools present',
                'isolated Blender addons', 'SOMA30 retarget and toe correction']), indent=2))
    say('PASS environment and Blender retarget verification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    try:
        # Prevent two installers from racing over archives/configuration.
        import msvcrt
        with (STATE / 'setup.lock').open('a+b') as lock:
            lock.seek(0)
            if not lock.read(1):
                lock.write(b'0'); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            if args.verify_only:
                verify(json.loads((STATE / 'config.json').read_text()))
            else:
                setup(args.fresh)
    except Exception as error:
        say('ERROR: ' + str(error))
        sys.exit(1)
