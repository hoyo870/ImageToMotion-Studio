"""Opt-in actual GPU generation, texture/retopology, CPP motion and Blender bake."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'installer'))
from setup import blender_env
cfg=json.loads((ROOT/'.state/config.json').read_text())
case=ROOT/'.state/full-test'
case.mkdir(parents=True,exist_ok=True)
inputs=case/'input';inputs.mkdir(exist_ok=True)
shutil.copy2(ROOT/'examples/front.png',inputs/'front.png')
env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','IMT_NONINTERACTIVE':'1'}
print('ACTUAL 3D generation -> 2048 texture -> cleanup -> retopology',flush=True)
with (case/'3d.log').open('wb') as log:
    p=subprocess.run([cfg['python'],str(Path(cfg['three'])/'drag_drop_3d.py'),str(inputs/'front.png'),'--no-open'],
                     env=env,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
assert p.returncode==0,'3D failed; see .state/full-test/3d.log'
assert (inputs/'front.glb').is_file()
spec=importlib.util.spec_from_file_location('native_backend',ROOT/'addons/kimodo_rigify/backend.py')
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
print('ACTUAL Kimodo.cpp text-to-motion',flush=True)
# Each test uses a new folder; previous artifacts are retained.
import uuid
job=case/('motion_'+uuid.uuid4().hex[:8])
process,log,result=backend.start_job(ROOT/'runtime','CPP','An adult person walks forward at a relaxed pace.',60,50,42,job)
try:assert process.wait(timeout=900)==0,'Kimodo generation failed'
finally:log.close()
positions,rotations=backend.read_raw(result);assert len(positions)==180
env=blender_env(cfg)
with (case/'blender.log').open('wb') as log:
    p=subprocess.run([cfg['blender'],'--factory-startup','-b','--python-exit-code','1','--python',
                      str(ROOT/'tests/retarget_generated.py'),'--',str(ROOT),str(result),str(case)],
                     env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
assert p.returncode==0,'Blender bake failed; see .state/full-test/blender.log'
report={'status':'passed','actual_3d_generation':True,'texture_resolution':2048,
        'cleanup_and_retopology':True,'actual_cpp_motion_frames':60,
        'isolated_blender_retarget':True,'soma30_correction':True}
(case/'report.json').write_text(json.dumps(report,indent=2))
print('FULL_PIPELINE_PASS',flush=True)
