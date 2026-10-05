"""Open a completed editable model with this installation's Blender/addons."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent

def open_result(directory):
    directory=Path(directory).resolve()
    try:
        os.startfile(directory)
    except OSError as error:
        print(f'결과 폴더 열기 실패: {error}. 직접 열기: {directory}',flush=True)
    try:
        config_path=Path(os.environ.get('IMT_CONFIG_PATH',str(ROOT.parents[1]/'.state/config.json')))
        config=json.loads(config_path.read_text(encoding='utf-8'))
        choices=[Path(config['blender']),Path(config['post_blender'])]
        blender=next((p for p in choices if p.is_file()),None)
        if blender is None: raise FileNotFoundError('설정된 Blender 실행 파일이 없습니다.')
        model=directory/'retopology/model_final.blend'
        if not model.is_file(): raise FileNotFoundError(model)
        profile=Path(config['profile'])
        env={**os.environ,'BLENDER_USER_CONFIG':str(profile/'config'),
             'BLENDER_USER_SCRIPTS':str(profile/'scripts'),
             'BLENDER_USER_EXTENSIONS':str(profile/'extensions'),
             'IMT_RUNTIME_ROOT':str(Path(config['three']).parent),
             'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
        subprocess.Popen([str(blender),str(model),'--python',str(ROOT/'preview_model.py')],env=env)
    except Exception as error:
        print(f'Blender 자동 열기 실패 (생성 결과는 보존됨): {error}',flush=True)

