import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('open_result',Path(__file__).resolve().parents[1]/'pipeline/3d/open_result.py')
preview=importlib.util.module_from_spec(spec); spec.loader.exec_module(preview)

class OpenResultTests(unittest.TestCase):
    def check_launch(self,installed):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); output=root/'result'; (output/'retopology').mkdir(parents=True)
            model=output/'retopology/model_final.blend'; model.touch()
            system=root/'system.exe'; portable=root/'portable.exe'; portable.touch()
            if installed: system.touch()
            config=root/'config.json'
            config.write_text(json.dumps(dict(blender=str(system),post_blender=str(portable),profile=str(root/'profile'),three=str(root/'runtime/three'))))
            with patch.dict(os.environ,{'IMT_CONFIG_PATH':str(config)}),patch.object(preview.os,'startfile') as folder,patch.object(preview.subprocess,'Popen') as launch:
                preview.open_result(output)
            folder.assert_called_once_with(output)
            args=launch.call_args
            self.assertEqual(args.args[0][0],str(system if installed else portable))
            self.assertEqual(args.args[0][1],str(model))
            self.assertEqual(args.kwargs['env']['BLENDER_USER_SCRIPTS'],str(root/'profile/scripts'))
            self.assertNotIn('--background',args.args[0])

    def test_installed_blender_with_addon_profile(self): self.check_launch(True)
    def test_portable_fallback_with_addon_profile(self): self.check_launch(False)

if __name__=='__main__': unittest.main()
