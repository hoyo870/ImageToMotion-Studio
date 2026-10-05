import hashlib
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'installer'))
import setup

class InstallerTests(unittest.TestCase):
    def test_resume_corrupt_repair_and_skip(self):
        payload=b'ImageToMotion-verified-download'*1024
        calls=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                start=int(self.headers.get('Range','bytes=0-')[6:].split('-')[0])
                calls.append(start)
                self.send_response(206 if start else 200)
                if start:self.send_header('Content-Range',f'bytes {start}-{len(payload)-1}/{len(payload)}')
                self.send_header('Content-Length',str(len(payload)-start));self.end_headers()
                self.wfile.write(payload[start:])
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        old_state=setup.STATE
        try:
            with tempfile.TemporaryDirectory(prefix='imt test ') as tmp:
                setup.STATE=Path(tmp)
                item={'url':f'http://127.0.0.1:{server.server_port}/file','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
                dest=Path(tmp)/'image.bin';dest.write_bytes(b'corrupt')
                dest.with_name(dest.name+'.part').write_bytes(payload[:101])
                setup.download(item,dest)
                self.assertEqual(dest.read_bytes(),payload);self.assertEqual(calls,[101])
                setup.download(item,dest);self.assertEqual(calls,[101])
                # Same length but changed content must invalidate the hash cache.
                dest.write_bytes(b'x'*len(payload));self.assertFalse(setup.verified(dest,item))
        finally:
            setup.STATE=old_state;server.shutdown();server.server_close()

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'unsafe.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.txt','bad')
            with self.assertRaises(ValueError):setup.extract(archive,Path(tmp)/'inside')

    def test_pinned_models_and_portable_requirements(self):
        for item in setup.MODELS:
            self.assertEqual(len(item['sha256']),64)
            self.assertNotIn('/resolve/main/',item['url'])
            self.assertFalse(Path(item['destination']).is_absolute())
            self.assertNotIn('..',Path(item['destination']).parts)
        lock=(ROOT/'manifests/requirements-3d.lock').read_text()
        self.assertNotIn('file:///',lock);self.assertNotIn('C:/Users',lock)

if __name__=='__main__':unittest.main()
