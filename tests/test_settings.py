import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipeline/3d'))
from studio_settings import load_settings,effective_shape,DEFAULTS

class SettingsTests(unittest.TestCase):
    def test_ranges_and_models(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp)
            (root/'.env').write_text('MODEL_PROFILE=PIXAL3D_GGUF\nSINGLE_VERTEX_MIN=800\nSINGLE_VERTEX_MAX=1200\nMULTI_VERTEX_MIN=1800\nMULTI_VERTEX_MAX=2600\nINPUT_RESOLUTION=2048\nSHAPE_RESOLUTION=1536\n')
            cfg=load_settings(root)
            self.assertEqual(cfg['single_vertices'],[800,1200])
            self.assertEqual(cfg['multi_vertices'],[1800,2600])
            self.assertEqual(cfg['input_resolution'],2048)
            self.assertEqual(effective_shape(cfg,8192),1024)
            self.assertEqual(effective_shape(cfg,24576),1536)

    def test_invalid_settings_fail_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            root=Path(tmp)
            for text in ('SINGLE_VERTEX_MIN=1501\nSINGLE_VERTEX_MAX=1500','MODEL_PROFILE=wrong','INPUT_RESOLUTION=1234','SHAPE_RESOLUTION=512'):
                (root/'.env').write_text(text)
                with self.assertRaises(ValueError): load_settings(root)

    def test_process_override_and_vram_cap(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'MODEL_PROFILE':'TRELLIS2_GGUF','SHAPE_RESOLUTION':'2048'},clear=True):
            cfg=load_settings(tmp)
            self.assertEqual(effective_shape(cfg,8192),1024)
            self.assertEqual(effective_shape(cfg,16384),1536)

class PreparedInputTests(unittest.TestCase):
    def test_large_input_keeps_mapping_at_2048(self):
        from PIL import Image
        import drag_drop_3d
        for resolution in (1536,2048):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); src=root/'original.png'; target=root/'front_shape.png'
                Image.new('RGB',(320,180),'red').save(src)
                with patch.object(drag_drop_3d,'settings',return_value={'input_resolution':resolution}):
                    record=drag_drop_3d.prepare_inputs(src,target)
                with Image.open(target) as im: self.assertEqual(im.size,(resolution,resolution))
                with Image.open(root/'front_2048.png') as im: self.assertEqual(im.size,(2048,2048))
                with Image.open(src) as im: self.assertEqual(im.size,(320,180))
                self.assertEqual(record['input_resolution'],resolution)

    def test_job_budget_remains_frozen(self):
        import json,studio_settings
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'settings.json').write_text(json.dumps({'single_vertices':[750,1100]}))
            with patch.object(studio_settings,'settings',return_value={'single_vertices':[1000,1500]}):
                self.assertEqual(studio_settings.vertex_budget('single',root),(750,1100))

if __name__=='__main__': unittest.main()
