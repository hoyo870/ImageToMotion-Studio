import pathlib,json,hashlib,torch
from safetensors import safe_open
from safetensors.torch import save_file
root=pathlib.Path(__file__).parent; models=root/'ComfyUI/models'; repo=models/'visualbruno/TRELLIS.2-4B-FP8'; stem=repo/'ckpts_local/shape_dec_native_fp16';stem.parent.mkdir(exist_ok=True)
native=models/'vae/trellis_2_shape_vae_bf16.safetensors'; old=repo/'ckpts_fp8/shape_dec_next_dc_f16c32_fp8'
with safe_open(native,framework='pt') as sf:
 weights={k.removeprefix('shape_dec.'):sf.get_tensor(k).to(torch.float16).contiguous() for k in sf.keys() if k.startswith('shape_dec.')}
 assert weights, 'Native shape decoder has no tensors'
save_file(weights,str(stem)+'.safetensors')
cfg=json.loads(pathlib.Path(str(old)+'.json').read_text());cfg['args'].pop('use_fp8',None);cfg['args']['use_fp16']=True
pathlib.Path(str(stem)+'.json').write_text(json.dumps(cfg,indent=2))
configpath=repo/'pipeline_fp8.json';backup=repo/'pipeline_fp8.downloaded.json'
if not backup.exists(): backup.write_bytes(configpath.read_bytes())
pipeline=json.loads(backup.read_text());pipeline['args']['models']['shape_slat_decoder']='ckpts_local/shape_dec_native_fp16'
pipeline['args']['models']['sparse_structure_decoder']=str((models/'microsoft/TRELLIS-image-large/ckpts/ss_dec_conv3d_16l8_fp16').resolve()).replace('\\','/')
configpath.write_text(json.dumps(pipeline,indent=2))
record=dict(source=str(native),derived=str(stem)+'.safetensors',conversion='shape_dec prefix removed; native BF16 tensors converted to FP16',bytes=pathlib.Path(str(stem)+'.safetensors').stat().st_size)
(root/'nohair_decoder_override.json').write_text(json.dumps(record,indent=2));print(record)
