"""Compile a real Triton kernel; imports alone miss embedded Python headers."""
import torch
import triton
import triton.language as tl

@triton.jit
def increment(values):
    ids=tl.arange(0,32)
    tl.store(values+ids,tl.load(values+ids)+1.0)

values=torch.ones(32,device='cuda')
increment[(1,)](values)
torch.cuda.synchronize()
assert torch.equal(values,torch.full_like(values,2))
print('CUDA_TRITON_COMPILE_PASS')
