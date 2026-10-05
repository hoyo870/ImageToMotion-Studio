"""Shape fallback must never hide unrelated Blender errors or old rejections."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('retopo_pipeline',Path(__file__).resolve().parents[1]/'pipeline/3d/retopo_pipeline.py')
pipeline=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class RetopologyTests(unittest.TestCase):
    def check_failure(self,shape_rejected,timeout=False,repaired=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); case=root/'case'; output=case/'retopology'
            output.mkdir(parents=True); (case/'cleanup').mkdir()
            for path in (root/'tools/InstantMeshes/Instant Meshes.exe',root/'Blender/blender-4.5.9-windows-x64/blender.exe',
                         case/'model_textured.glb',case/'cleanup/geometry_for_retopology.obj'):
                path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'test')
            (case/'cleanup/cleanup_report.json').write_text(json.dumps({'objects':[{'after':{'multi_face_edges':int(repaired)}}]}))
            # Old markers must not cause a new non-shape error to trigger fallback.
            (output/'shape_rejected.json').write_text('{}')
            calls=[]
            def run(command,**kwargs):
                calls.append(command)
                if any(str(arg).endswith('prepare_retopology.py') for arg in command):
                    (output/'retopo_input.obj').write_text('v 0 0 0\n'*1200)
                    return SimpleNamespace(returncode=0)
                if '-o' in command:
                    if timeout: raise pipeline.subprocess.TimeoutExpired(command,120)
                    Path(command[command.index('-o')+1]).write_text('v 0 0 0\n'*1200)
                    return SimpleNamespace(returncode=0)
                if command[command.index('--method')+1]=='instant_meshes' and shape_rejected:
                    (output/'shape_rejected.json').write_text('{"max_relative":0.1}')
                if repaired and command[command.index('--method')+1]=='surface_fallback':
                    kwargs['stdout'].write(b'ValueError: Final geometric vertex budget exceeded: 1658\n')
                return SimpleNamespace(returncode=1)
            with patch.object(pipeline,'ROOT',root),patch.object(pipeline,'preflight_tools'),patch.object(pipeline.subprocess,'run',side_effect=run):
                with self.assertRaises(RuntimeError) as error:
                    pipeline.run_retopology(case,'single')
            self.assertEqual(len(calls),5 if repaired else 3 if shape_rejected else 2)
            if repaired:
                self.assertIn(str(case/'cleanup/geometry_for_retopology.obj'),calls[-1])
            if timeout: self.assertIn('surface_fallback',calls[-1])
            if shape_rejected:
                self.assertIn('surface_fallback',calls[-1])
                self.assertIn('후처리 실패',str(error.exception))
            else:
                self.assertIn('후처리 실패',str(error.exception))
            self.assertEqual((case/'model_textured.glb').read_bytes(),b'test')

    def test_shape_rejection_retries_source_surface(self):
        self.check_failure(True)

    def test_unrelated_error_does_not_use_stale_rejection(self):
        self.check_failure(False)

    def test_instant_meshes_timeout_uses_validated_fallback(self):
        self.check_failure(False,timeout=True)

    def test_voxel_budget_failure_retries_cleaned_original(self):
        self.check_failure(True,repaired=True)

    def test_error_message_reports_actual_blender_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'한글 로그.txt'
            path.write_text('noise\nValueError: Final geometric vertex budget exceeded: 1658\nBlender quit\n',encoding='utf-8')
            self.assertIn('1658',pipeline.blender_failure(path))


if __name__=='__main__': unittest.main()
