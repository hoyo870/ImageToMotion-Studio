import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'installer'))
import torch
import torch.nn.functional as F
from gguf_compat import na2d_exact

class NAFCompatibilityTests(unittest.TestCase):
    def test_noninteger_resize_matches_full_reference(self):
        torch.manual_seed(41)
        q=torch.rand(1,12,14,2,4);k=torch.rand(1,5,4,2,4);v=torch.rand(1,5,4,2,6)
        result=na2d_exact(q,k,v,(3,3),(2,3),0.5,tile=5,v_chunk=2)
        def windows(x,channels):
            full=F.interpolate(x.permute(0,3,4,1,2).reshape(2,channels,5,4),size=(12,14),mode='nearest-exact')
            return F.unfold(full,kernel_size=3,dilation=(2,3),padding=(2,3)).reshape(1,2,channels,9,168).permute(0,1,4,3,2)
        qw=q.permute(0,3,1,2,4).reshape(1,2,168,1,4)
        attention=(torch.matmul(qw,windows(k,4).transpose(-1,-2))*0.5).softmax(-1)
        expected=torch.matmul(attention,windows(v,6)).squeeze(-2).reshape(1,2,12,14,6).permute(0,1,4,2,3)
        torch.testing.assert_close(result,expected)

if __name__=='__main__': unittest.main()
