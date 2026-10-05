"""Validated repository .env settings; no shell evaluation or external dependency."""
from functools import lru_cache
import json,os,subprocess
from pathlib import Path

DEFAULTS=dict(MODEL_PROFILE='TRELLIS2_FP8',GGUF_QUANT='Q4_K_M',
    SINGLE_VERTEX_MIN='1000',SINGLE_VERTEX_MAX='1500',MULTI_VERTEX_MIN='2000',MULTI_VERTEX_MAX='3000',
    INPUT_RESOLUTION='1024',SHAPE_RESOLUTION='1024',TEXTURE_RESOLUTION='2048')

def repository_root():
    if os.environ.get('IMT_CONFIG_PATH'): return Path(os.environ['IMT_CONFIG_PATH']).resolve().parents[1]
    for parent in Path(__file__).resolve().parents:
        if (parent/'installer/launch.py').is_file(): return parent
    return Path(__file__).resolve().parent

def load_settings(root=None):
    root=Path(root) if root else repository_root()
    values=DEFAULTS.copy(); path=root/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            key,sep,value=line.partition('=')
            if not sep or key.strip() not in DEFAULTS: raise ValueError('알 수 없는 .env 설정: '+line)
            values[key.strip()]=value.strip().strip('\"\'')
    values.update({k:os.environ[k] for k in DEFAULTS if k in os.environ})
    if values['MODEL_PROFILE'] not in ('TRELLIS2_FP8','TRELLIS2_GGUF','PIXAL3D_GGUF'):
        raise ValueError('MODEL_PROFILE: TRELLIS2_FP8 / TRELLIS2_GGUF / PIXAL3D_GGUF')
    if values['GGUF_QUANT']!='Q4_K_M': raise ValueError('현재 검증 다운로드 프로필은 GGUF_QUANT=Q4_K_M입니다.')
    result=dict(model_profile=values['MODEL_PROFILE'],quant=values['GGUF_QUANT'])
    for mode in ('single','multi'):
        lo=int(values[mode.upper()+'_VERTEX_MIN']); hi=int(values[mode.upper()+'_VERTEX_MAX'])
        if not 4<=lo<=hi<=500000: raise ValueError(mode+' 정점 범위: 4 <= 최소 <= 최대 <= 500000')
        result[mode+'_vertices']=[lo,hi]
    for key in ('INPUT_RESOLUTION','SHAPE_RESOLUTION'):
        value=int(values[key])
        if value not in (1024,1536,2048): raise ValueError(key+': 1024 / 1536 / 2048')
        result[key.lower()]=value
    if int(values['TEXTURE_RESOLUTION'])!=2048: raise ValueError('투영 텍스처는 현재 2048을 사용합니다.')
    result['texture_resolution']=2048
    return result

@lru_cache(maxsize=1)
def settings(): return load_settings()

def vertex_budget(mode,directory=None):
    if mode not in ('single','multi'): raise ValueError('Unknown view mode')
    cfg=settings()
    path=Path(directory)/'settings.json' if directory else None
    if path and path.is_file(): cfg=json.loads(path.read_text(encoding='utf-8'))
    return tuple(cfg[mode+'_vertices'])

def effective_shape(cfg,vram_mb=None):
    if vram_mb is None:
        query=subprocess.check_output(['nvidia-smi','--query-gpu=memory.total','--format=csv,noheader,nounits'],text=True)
        vram_mb=int(query.splitlines()[0].strip())
    cap=1024 if vram_mb<12000 else 1536 if vram_mb<24000 else 2048
    if cfg['model_profile']=='PIXAL3D_GGUF' and vram_mb<24000: cap=1024
    # Installed upstream nodes expose up to 1536; 2048 input remains supported.
    cap=min(cap,1536)
    return min(cfg['shape_resolution'],cap)
