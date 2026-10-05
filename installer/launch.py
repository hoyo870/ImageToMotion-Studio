import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'installer'))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['menu','3d','blender','verify','results'])
    parser.add_argument('arguments',nargs='*')
    opts,extra=parser.parse_known_args()
    p=ROOT/'.state/config.json'
    if not p.exists():
        print('Run setup.bat first.');return 1
    config=json.loads(p.read_text(encoding='utf-8'))
    if opts.action=='menu':
        print('1: Generate 3D (drag images onto generate_3d.bat)\n2: Blender + Kimodo\n3: Example results\n4: Verify installation')
        choice=input('Select: ').strip()
        opts.action={'1':'3d','2':'blender','3':'results','4':'verify'}.get(choice,'results')
    if opts.action=='verify':
        from setup import verify
        verify(config);return 0
    if opts.action=='blender':
        from setup import blender_env
        cmd=[config['blender']]+opts.arguments
        subprocess.Popen(cmd,env=blender_env(config));return 0
    if opts.action=='results':
        os.startfile(ROOT/'examples/index.html');return 0
    if not opts.arguments:
        print('Drag one image, or front/back/left/right images together onto generate_3d.bat.');return 1
    return subprocess.call([config['python'],str(Path(config['three'])/'drag_drop_3d.py')]+opts.arguments+extra,
                           env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:print('ERROR:',error);sys.exit(1)
