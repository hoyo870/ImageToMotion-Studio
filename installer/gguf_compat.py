# SPDX-License-Identifier: GPL-3.0-only
# ComfyUI-derived attention code; full license: vendor/licenses/ComfyUI-GPL-3.txt
"""Use ComfyUI's official pure Torch NAF implementation on Windows."""
from pathlib import Path
from types import MethodType
import torch
import torch.nn.functional as F
from typing import Tuple

def wrap_pixal_factory(factory):
    def build(*args, **kwargs):
        model=factory(*args, **kwargs)
        def load_naf(instance):
            if instance.naf_model is not None: return
            import comfy.image_encoders.naf as naf_module
            naf_module.na2d_pure=na2d_exact
            from comfy.image_encoders.naf import NAF
            import comfy.ops
            path=Path(__file__).resolve().parents[3]/'gguf_models/aux/naf_release.pth'
            net=NAF(operations=comfy.ops.manual_cast).eval()
            net.load_state_dict(torch.load(path,map_location='cpu',weights_only=True),strict=True)
            net.requires_grad_(False)
            device=next(instance.model.parameters()).device
            instance.naf_model=net.to(device=device,dtype=torch.float16)
        model._load_naf=MethodType(load_naf,model)
        return model
    return build

# Neighborhood attention adapted from ComfyUI (GPL-3.0); NAF architecture/weights Apache-2.0.
def na2d_exact(
        q: torch.Tensor,                # [B, H, W, n_heads, d_qk] at HR.
        k_lr: torch.Tensor,             # [B, h_lr, w_lr, n_heads, d_qk] at LR
        v_lr: torch.Tensor,             # [B, h_lr, w_lr, n_heads, d_v] at LR
        kernel_size: Tuple[int, int],   # (Kh, Kw) attention window.
        dilation: Tuple[int, int],      # (Dh, Dw) stride within the unrolled K/V grid; also the LR→HR upsample factor.
        scale: float,                   # 1 / sqrt(d_qk) scaling for the Q·K scores.
        tile: int = 128,                # Spatial tile size (output positions per tile)
        v_chunk: int = 64,              # Sub-divide d_v into chunks of this size when computing attn·V. None disables chunking.
        output: torch.Tensor = None,    # Pre-allocated [B, n_heads, d_v, H, W] buffer (may be on CPU).
    ) -> torch.Tensor:                  # [B, n_heads, d_v, H, W] (caller views as BCHW).
    """Neighborhood attention in pure torch via F.unfold + per-tile slicing.

    K and V are passed at LR resolution and upsampled (nearest-exact) per-tile only
    for the slice the unfold needs. Avoids the [B, n*d, H, W] HR allocations for K
    (512 MB) and V (2 GB) at tex_1024 fp16. Spatial tiling bounds the per-tile
    F.unfold blob; `v_chunk` further slices d_v so attn·V is computed in C-sized
    chunks (attn is reused, computed once from Q/K).

    """
    B, H, W, n, d_qk = q.shape
    def nearest_slice(src, dh, dw, hs, ws):
        # Match nearest-exact resize to the requested HR dimensions even for
        # cropped NAF tiles whose LR/HR sizes have a noninteger ratio.
        rows=torch.floor((torch.arange(hs[0],hs[1],device=src.device)+0.5)*src.shape[1]/H).long().clamp(max=src.shape[1]-1)
        cols=torch.floor((torch.arange(ws[0],ws[1],device=src.device)+0.5)*src.shape[2]/W).long().clamp(max=src.shape[2]-1)
        x=src.index_select(1,rows).index_select(2,cols)
        return x.permute(0,3,4,1,2).reshape(src.shape[0]*src.shape[3],src.shape[4],len(rows),len(cols))
    d_v = v_lr.shape[-1]
    Kh, Kw = kernel_size
    Dh, Dw = dilation
    pad_h, pad_w = (Kh // 2) * Dh, (Kw // 2) * Dw

    out = output if output is not None else torch.empty((B, n, d_v, H, W), device=q.device, dtype=q.dtype)

    th = min(tile, H) if tile else H
    tw = min(tile, W) if tile else W
    chunk = v_chunk if (v_chunk and v_chunk < d_v) else d_v

    for h0 in range(0, H, th):
        for w0 in range(0, W, tw):
            h1, w1 = min(h0 + th, H), min(w0 + tw, W)
            t_h, t_w = h1 - h0, w1 - w0

            # Padded HR region the unfold needs (kernel span = (K-1)*D + 1).
            h_src_start = max(0, h0 - pad_h)
            h_src_end   = min(H, h1 + pad_h)
            w_src_start = max(0, w0 - pad_w)
            w_src_end   = min(W, w1 + pad_w)
            pad_top = max(0, pad_h - h0)
            pad_bot = max(0, (h1 + pad_h) - H)
            pad_lft = max(0, pad_w - w0)
            pad_rgt = max(0, (w1 + pad_w) - W)

            # Upsample only the tile region from k_lr / v_lr.
            k_tile = nearest_slice(k_lr, Dh, Dw,
                                        (h_src_start, h_src_end),
                                        (w_src_start, w_src_end))
            v_tile = nearest_slice(v_lr, Dh, Dw,
                                        (h_src_start, h_src_end),
                                        (w_src_start, w_src_end))
            if pad_top or pad_bot or pad_lft or pad_rgt:
                k_tile = F.pad(k_tile, [pad_lft, pad_rgt, pad_top, pad_bot])
                v_tile = F.pad(v_tile, [pad_lft, pad_rgt, pad_top, pad_bot])

            # Q·K → attention weights (small: KK=81 per output position).
            KK = Kh * Kw
            k_w = F.unfold(k_tile, kernel_size=(Kh, Kw), dilation=(Dh, Dw), padding=0)
            k_w = k_w.view(B, n, d_qk, KK, t_h * t_w).permute(0, 1, 4, 3, 2)  # [B, n, t, KK, d_qk]
            # q is [B, H, W, n, d_qk]; per-tile slice + permute -> [B, n, t_h*t_w, 1, d_qk].
            q_tile = q[:, h0:h1, w0:w1].permute(0, 3, 1, 2, 4).reshape(B, n, t_h * t_w, 1, d_qk)
            scores = torch.matmul(q_tile, k_w.transpose(-1, -2)) * scale
            attn = scores.softmax(dim=-1)
            del k_w, scores, q_tile, k_tile

            # attn · V, chunked over d_v.
            for c0 in range(0, d_v, chunk):
                c1 = min(c0 + chunk, d_v)
                v_w = F.unfold(v_tile[:, c0:c1], kernel_size=(Kh, Kw),dilation=(Dh, Dw), padding=0) # [B*n, (c1-c0)*KK, t]
                v_w = v_w.view(B, n, c1 - c0, KK, t_h * t_w).permute(0, 1, 4, 3, 2)
                out_chunk = torch.matmul(attn, v_w).squeeze(-2) # [B, n, t, c1-c0]
                out_chunk = out_chunk.view(B, n, t_h, t_w, c1 - c0).permute(0, 1, 4, 2, 3)
                out[:, :, c0:c1, h0:h1, w0:w1] = out_chunk
                del v_w, out_chunk
            del attn, v_tile

    return out  # [B, n, d_v, H, W] — sole caller (CrossAttention) views it as BCHW directly.
