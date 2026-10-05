"""Check pinned model URLs without downloading multi-gigabyte weights."""
from pathlib import Path
import concurrent.futures
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
items=json.loads((ROOT/'manifests/models.json').read_text())
def check(item):
    p=subprocess.run(['curl.exe','-fLsSI','--retry','2','--max-time','60',item['url']],
                     capture_output=True,timeout=190)
    if p.returncode:raise RuntimeError('Unavailable model URL: '+item['destination'])
    lengths=[int(line.split(':',1)[1]) for line in p.stdout.decode().splitlines()
             if line.lower().startswith('content-length:')]
    if lengths and lengths[-1]!=item['bytes']:
        raise RuntimeError('Model URL size mismatch: '+item['destination'])
    return {'file':item['destination'],'accessible':True}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(check,items))
(ROOT/'.state/download-url-checks.json').write_text(json.dumps(results,indent=2))
print('PINNED_MODEL_URLS_PASS',len(results))
