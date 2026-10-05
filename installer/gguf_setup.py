"""Install selected pinned GGUF model, without altering shared Python/models."""
import json,re,shutil
from pathlib import Path
from setup import ROOT,MANIFEST,MODELS,download,snapshot,run,reuse_model

def ensure_gguf(config,profile=None):
    import sys
    sys.path.insert(0,str(ROOT/'pipeline/3d'))
    from studio_settings import load_settings
    profile=profile or load_settings(ROOT)['model_profile']
    if profile=='TRELLIS2_FP8': return
    three=Path(config['three']); destination=three/'ComfyUI/custom_nodes/ComfyUI-Trellis2-GGUF'
    snapshot('gguf-ops',three/'ComfyUI/custom_nodes/ComfyUI-GGUF')
    ops_init=three/'ComfyUI/custom_nodes/ComfyUI-GGUF/__init__.py'
    prefix="import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parents[3]/'gguf_deps'))\n"
    ops_text=ops_init.read_text(encoding='utf-8')
    if not ops_text.startswith(prefix): ops_init.write_text(prefix+ops_text,encoding='utf-8')
    marker=destination/'imt_patched.json'
    if not marker.is_file():
        snapshot('trellis-gguf',destination)
        init=destination/'__init__.py'
        init.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parents[3]/'gguf_deps'))\n"+init.read_text(encoding='utf-8'),encoding='utf-8')
        manager=destination/'model_manager.py'
        text=manager.read_text(encoding='utf-8')
        text=text.replace('return os.path.join(folder_paths.models_dir, dir_name)',
            "return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'gguf_models', dir_name)")
        manager.write_text(text,encoding='utf-8')
        pipeline=destination/'trellis2_gguf/pipelines/trellis2_image_to_3d.py'
        text=pipeline.read_text(encoding='utf-8').replace("elif pipeline_type == '2048_cascade':","elif pipeline_type in ('1536_cascade', '2048_cascade'):")
        text=text.replace('512, 2048,',"512, int(pipeline_type.split('_')[0]),")
        pipeline.write_text(text,encoding='utf-8')
        marker.write_text(json.dumps({'revision':MANIFEST['trellis-gguf']['revision'],'patches':['isolated deps/models','1536 cascade routing']}))
    utils=destination/'trellis2_gguf/utils/gguf_utils.py'
    text=re.sub(r'os.path.join\(os.path.dirname\(__file__\), (?:"\.\.",? ?)+\)', 'os.path.join(os.path.dirname(__file__), "..", "..", "..")',utils.read_text(encoding='utf-8'))
    utils.write_text(text,encoding='utf-8')
    shutil.copy2(ROOT/'installer/gguf_compat.py',destination/'imt_gguf_compat.py')
    pipeline=destination/'trellis2_gguf/pipelines/trellis2_image_to_3d.py'
    text=pipeline.read_text(encoding='utf-8')
    if 'wrap_pixal_factory(func)' not in text:
        text=text.replace('                        return func','                        from ...imt_gguf_compat import wrap_pixal_factory\n                        return wrap_pixal_factory(func)')
    if 'Optional MoGe disabled' not in text:
        text=text.replace('    def load_moge_model(self):','    def load_moge_model(self):\n        raise RuntimeError("Optional MoGe disabled; use fixed camera defaults without unpinned downloads")')
    pipeline.write_text(text,encoding='utf-8')
    if profile=='PIXAL3D_GGUF': download(MANIFEST['naf-weights'],three/'gguf_models/aux/naf_release.pth')
    wheel=ROOT/'.state/downloads'/MANIFEST['gguf-wheel']['filename']
    download(MANIFEST['gguf-wheel'],wheel)
    deps=three/'gguf_deps'
    if not (deps/'gguf').is_dir():
        run([config['python'],'-m','pip','install','--no-deps','--target',deps,wheel])
    profiles=json.loads((ROOT/'manifests/gguf-models.json').read_text())
    selected=profiles[profile]; folder=three/'gguf_models'/selected['directory']
    # Reuse identical decoder files, including weights installed for another GGUF model.
    candidates={i['sha256']:three/'ComfyUI/models'/i['destination'] for i in MODELS if i['component']=='3d'}
    for other in profiles.values():
        candidates.update({i['sha256']:three/'gguf_models'/other['directory']/i['destination'] for i in other['files'] if (three/'gguf_models'/other['directory']/i['destination']).is_file()})
    for item in selected['files']:
        target=folder/item['destination']
        cached=candidates.get(item['sha256'])
        if cached and cached!=target and cached.is_file(): reuse_model(item,target,cached)
        download(item,target)
    print('GGUF_READY: '+profile,flush=True)
