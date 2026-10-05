import numpy as np
import torch
from PIL import Image
import nodes
from . import identity

class MappingCropRGBA:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"image":("IMAGE",),"mask":("MASK",)}}
    RETURN_TYPES=("IMAGE",)
    FUNCTION="process"
    CATEGORY="Local 3D"
    def process(self,image,mask):
        rgb=Image.fromarray((image[0,:,:,:3].cpu().numpy().clip(0,1)*255).astype(np.uint8))
        alpha=Image.fromarray((mask[0].cpu().numpy().clip(0,1)*255).astype(np.uint8)).resize(rgb.size,Image.Resampling.BILINEAR)
        box=alpha.point(lambda x:255 if x>127 else 0).getbbox()
        if box is None: raise ValueError("No foreground mask")
        x0,y0,x1,y1=box; side=int(max(x1-x0,y1-y0)*1.1)
        cx=(x0+x1)/2;cy=(y0+y1)/2
        rgba=rgb.convert("RGBA");rgba.putalpha(alpha)
        rgba=rgba.crop((int(cx-side/2),int(cy-side/2),int(cx-side/2)+side,int(cy-side/2)+side)).resize((2048,2048),Image.Resampling.LANCZOS)
        return (torch.from_numpy(np.array(rgba).astype(np.float32)/255)[None],)

class SourceProjection2048:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"trimesh":("TRIMESH",)},"optional":{v+"_image":("IMAGE",) for v in ("front","back","left","right")}}
    RETURN_TYPES=("TRIMESH","IMAGE","IMAGE")
    FUNCTION="process"
    CATEGORY="Local 3D"
    def process(self,trimesh,**images):
        verts=np.asarray(trimesh.vertices); center=(verts.min(0)+verts.max(0))/2
        radius=np.linalg.norm(verts-center,axis=1).max()
        scale=1.15/(2*radius)
        ortho=float(np.ptp(verts,axis=0).max()*scale*1.1)
        import gc
        import comfy.model_management
        from .projection_guarded import texture_mesh_with_multiview
        comfy.model_management.unload_all_models();gc.collect();torch.cuda.empty_cache()
        prepared=[];azimuths=[]
        extent=np.ptp(verts,axis=0);overall=extent.max()
        for view,az in (("front",0),("back",180),("left",90),("right",270)):
            tensor=images.get(view+"_image")
            if tensor is None:continue
            pil=Image.fromarray((tensor[0].cpu().numpy().clip(0,1)*255).astype(np.uint8))
            view_extent=max(extent[1],extent[0] if view in ("front","back") else extent[2])
            pixels=max(32,round(2048*view_extent/overall))
            small=pil.resize((pixels,pixels),Image.Resampling.LANCZOS)
            canvas=Image.new("RGBA",(2048,2048),(0,0,0,0));canvas.paste(small,((2048-pixels)//2,(2048-pixels)//2))
            prepared.append(canvas);azimuths.append(az)
        mesh,base,mr=texture_mesh_with_multiview(trimesh,prepared,azimuths,[0]*len(prepared),[1.0]*len(prepared),texture_size=2048,blend_texture=True,blend_exponent=4.0,ortho_scale=ortho,norm_size=1.15,fill_holes=True,max_hole_size=20,use_metallic=False,depth_eps=.01,mesh_cluster_threshold_cone_half_angle_rad=60,add_alpha_channel=False)
        return mesh,torch.from_numpy(np.array(base).astype(np.float32)/255)[None],torch.from_numpy(np.array(mr).astype(np.float32)/255)[None]

NODE_CLASS_MAPPINGS={"LocalMappingCropRGBA":MappingCropRGBA,"LocalSourceProjection2048":SourceProjection2048}
