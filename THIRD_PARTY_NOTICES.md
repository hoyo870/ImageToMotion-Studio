# Third-party notices

The top-level Apache-2.0 license applies to original installer/pipeline code and Kimodo integration. It does not replace any third-party or model license.

| Component | Source / terms |
|---|---|
| Python | https://www.python.org/ — PSF license, downloaded unmodified |
| Python 3.12 JIT headers/import library | PSF license; small include/libs archive accompanies embedded Python for Triton compilation; Python license retained in runtime |
| ComfyUI | https://github.com/Comfy-Org/ComfyUI — upstream GPL license retained in installed snapshot |
| TRELLIS.2 wrapper | https://github.com/visualbruno/ComfyUI-Trellis2 — upstream LICENSE retained; native wheels retain their licenses |
| Local texture projection adaptation | Based on ComfyUI-Trellis2 texture_projection_multiview.py; MIT copyright retained in addons/comfyui-local-dual-resolution/LICENSE |
| Blender | https://www.blender.org/ — GPL, downloaded from official release server, unmodified |
| Mixamo Rig | https://github.com/tdw46/mixamo_blender4-main — GPL-3.0-or-later; complete installed 1.2.2 Python source is in addons/mixamo_rig |
| Instant Meshes | https://github.com/wjakob/instant-meshes — original runtime and BSD license text in vendor/licenses/InstantMeshes.txt |
| kimodo.cpp | https://github.com/localai-org/kimodo.cpp/tree/5679ff19ba0a522c0b0516e9a9d402fe1af2c027 — Apache-2.0, compiled Windows runtime bundled with license |
| GGML | Pinned submodule of kimodo.cpp — MIT, license in bundled runtime |
| GCC runtime DLLs | GCC 16.2.0 via WinLibs; GPL-3/LGPL-3 with GCC Runtime Library Exception, license texts in vendor/licenses |
| MinGW-w64 runtime DLLs | MinGW-w64 14.0.0 via WinLibs, license text in vendor/licenses |
| dlfcn-win32 libdl DLL | https://github.com/dlfcn-win32/dlfcn-win32 — MIT, license in vendor/licenses/dlfcn-win32.txt |

The bundled kimodo.cpp runtime was built from the commit above, with its pinned GGML submodule, MinGW-w64 UCRT 14.0.0 / GCC 16.2.0, Release + Vulkan enabled. DLLs are included to avoid requiring end users to compile C++.

ImageToMotion Studio embeds a UTF-8 process manifest in the two CLI executables to support Unicode Windows paths. This is a resource-only modification; the reproducible patch script and manifest are in installer/. Original upstream source code and model weights are unchanged. Windows 10 1903+ is required.

Corresponding upstream runtime sources: https://github.com/gcc-mirror/gcc/releases/tag/releases/gcc-16.2.0 and https://github.com/mingw-w64/mingw-w64/tree/v14.0.0. WinLibs build provenance: https://winlibs.com/. Original license texts accompany the runtime DLLs.

Models are NOT redistributed in this Git repository. Immutable revisions, file sizes and SHA256 values are recorded in manifests/models.json. Review each linked model card and its terms before use:

- https://huggingface.co/visualbruno/TRELLIS.2-4B-FP8
- https://huggingface.co/visualbruno/dinov3-vitl16-pretrain-lvd1689m
- https://huggingface.co/microsoft/TRELLIS-image-large
- https://huggingface.co/Comfy-Org/Pixal3D
- https://huggingface.co/Comfy-Org/BiRefNet
- https://huggingface.co/LocalAI-io/Kimodo-SOMA-RP-v1.1-GGML
- https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML

Kimodo and Llama-derived weights retain upstream NVIDIA/Meta/model-specific terms; availability for download is not a substitute for those terms. Third-party providers may change availability. The installer never copies account tokens, login sessions or personal caches into the repository.

PixelArtistry reference: https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes. This package uses a separate validated 1024/2048 workflow; it does not redistribute PixelArtistry's installer or claim authorship of its work.
