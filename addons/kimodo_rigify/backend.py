"""Blender 환경과 분리된 로컬 Kimodo 실행. 다운로드와 인증 변경은 하지 않는다."""
import os
from pathlib import Path
import subprocess
import json
import struct
import math

DEFAULT_ROOT = os.environ.get('IMT_RUNTIME_ROOT', str(Path(__file__).resolve().parents[2] / 'runtime'))


def check_memory(backend):
    if os.name != 'nt':
        return
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (key, ctypes.c_uint64) for key in ('physical', 'available_physical', 'commit',
            'available_commit', 'virtual', 'available_virtual', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        required = (18 if backend == 'OFFICIAL' else 11) * 1024 ** 3
        if status.available_commit < required:
            raise RuntimeError(f'생성용 메모리가 부족합니다 (남은 용량 {status.available_commit / 1024**3:.1f}GiB). '
                               '공식 Kimodo 웹데모나 다른 생성 작업을 종료하고 다시 시도하세요.')


def paths(root):
    root = Path(root).expanduser().resolve()
    return root / 'Kimodo', root / 'KimodoCpp'


def validate(root, backend):
    official, cpp = paths(root)
    needed = ([official / '.venv/Scripts/python.exe', official / 'source/kimodo']
              if backend == 'OFFICIAL' else
              [cpp / 'source/build/release/kmd-generate.exe',
               cpp / 'source/models/kimodo-soma-rp-v1.1-f32.gguf',
               cpp / 'source/Llama-3-Kimodo-Q8_0.gguf', cpp / 'source/tokenizer.gguf'])
    for path in needed:
        if not path.exists():
            raise RuntimeError(f'설치 파일이 없습니다: {path}')
    if backend == 'OFFICIAL':
        cache = official / 'cache/huggingface/hub/models--meta-llama--Meta-Llama-3-8B-Instruct/snapshots'
        if not cache.exists() or not any(cache.rglob('model-00004-of-00004.safetensors')):
            raise RuntimeError('공식 Llama 모델 캐시가 없습니다. 기존 설치의 모델 다운로드를 완료하세요.')
    return official, cpp


def start_job(root, backend, prompt, frames, steps, seed, folder):
    official, cpp = validate(root, backend)
    check_memory(backend)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
    env = os.environ.copy()
    # 실행 중 다른 모션 모델이나 인코더를 자동으로 내려받지 않는다.
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1',
               PYTHONUNBUFFERED='1', TEXT_ENCODER_DEVICE='cpu', TEXT_ENCODER_MODE='local')
    if backend == 'OFFICIAL':
        cache = str(official / 'cache/huggingface/hub')
        env.update(HF_HUB_CACHE=cache, HUGGINGFACE_CACHE_DIR=cache,
                   kimodo_EMBED_CACHE_DIR=str(official / 'cache/embeddings'))
        env['PATH'] = str(official / 'tools/mingw64/bin') + os.pathsep + env.get('PATH', '')
        # 마침표가 여러 개인 설명도 하나의 모션으로 처리한다.
        (folder / 'meta.json').write_text(json.dumps({'text': prompt,
            'duration': (frames + 1e-6) / 30, 'diffusion_steps': steps, 'seed': seed,
            'num_samples': 1}, ensure_ascii=False), encoding='utf-8')
        argv = [str(official / '.venv/Scripts/python.exe'), '-m', 'kimodo.scripts.generate',
                '--input_folder', str(folder), '--model', 'Kimodo-SOMA-RP-v1.1',
                '--num_samples', '1', '--diffusion_steps', str(steps), '--seed', str(seed),
                '--bvh', '--bvh_standard_tpose', '--output', str(folder / 'motion')]
        cwd = official / 'source'
        result = folder / 'motion.bvh'
    else:
        env.update(KIMODO_BACKEND='vulkan', KIMODO_TEXT_LAYER_CHUNK='8',
                   KIMODO_TEXT_RESIDENT_LIMIT_MIB='4000')
        env['PATH'] = str(cpp / 'source/build/release/bin') + os.pathsep + env.get('PATH', '')
        argv = [str(cpp / 'source/build/release/kmd-generate.exe'),
                str(cpp / 'source/models/kimodo-soma-rp-v1.1-f32.gguf'),
                str(cpp / 'source/Llama-3-Kimodo-Q8_0.gguf'), str(folder / 'prompt.txt'),
                str(frames), str(steps), str(seed), str(folder / 'raw')]
        cwd = cpp / 'source'
        result = folder / 'raw'
    (folder / 'request.json').write_text(json.dumps(dict(backend=backend, prompt=prompt,
        frames=frames, steps=steps, seed=seed), ensure_ascii=False, indent=2), encoding='utf-8')
    log = (folder / 'generation.log').open('wb')
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        log.close()
        raise
    return process, log, result


def read_floats(path):
    data = Path(path).read_bytes()
    if len(data) % 4:
        raise ValueError('모션 데이터 길이가 올바르지 않습니다.')
    values = struct.unpack('<' + 'f' * (len(data) // 4), data)
    if not all(math.isfinite(v) for v in values):
        raise ValueError('모션에 유효하지 않은 수치가 있습니다.')
    return values


def read_raw(folder):
    p = read_floats(Path(folder) / 'root_positions.f32')
    q = read_floats(Path(folder) / 'local_rotations_xyzw.f32')
    if not p or len(p) % 3 or len(q) != len(p) // 3 * 30 * 4:
        raise ValueError('SOMA 30관절 모션 형식이 아닙니다.')
    return p, q
