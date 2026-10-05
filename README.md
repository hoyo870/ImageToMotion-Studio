# ImageToMotion Studio

Windows에서 이미지 → 텍스처가 포함된 3D → 메시 정리·리토폴로지 → 리깅된 모델의 Kimodo 모션 적용을 위한 설치·실행 도구입니다.

## 시작

1. 이 저장소를 clone하거나 ZIP으로 내려받아 압축을 풉니다.
2. `setup.bat`을 실행합니다. 관리자 권한이나 시스템 Python 변경은 필요하지 않습니다.
3. 완료 후 `launcher.bat` 또는 아래 실행 파일을 사용합니다.

| 파일 | 기능 |
|---|---|
| `generate_3d.bat` | 이미지 드래그 → 3D·텍스처·메시 정리·리토폴로지 |
| `launch_blender.bat` | 전용 설정과 Kimodo/Mixamo Rig/Rigify 애드온으로 Blender 실행 |
| `view_results.bat` | 함께 제공한 결과 미리보기 |
| `verify.bat` | Python·패키지·GPU·모델·Blender 애드온 검증 |
| `run_generation_test.bat` | 실제 3D 생성 및 별도 리깅 샘플의 Kimodo 모션 생성 테스트 |

설치에 실패했다면 `.state/setup.log`를 확인하고 같은 `setup.bat`을 다시 실행하세요. 다운로드를 재개하고 검증된 파일은 건너뜁니다. 실행 상태·개인 경로는 `.state/`에만 저장되며 Git에 포함되지 않습니다.

## 지원 범위

- Windows 10 1903 이상 / Windows 11 x64, NVIDIA GPU, VRAM 8GB 이상.
- 첫 프로필은 CUDA compute capability major 7~9용 Python 3.12 / PyTorch 2.8.0+cu128입니다. RTX 50 계열, AMD, macOS는 이 릴리스에서 지원하지 않습니다.
- RTX 3070 Ti 8GB에서 검증합니다. 다른 GPU의 동일 결과·속도까지 보장하지 않습니다.
- 여유 디스크 40GB 이상, 시스템 RAM 32GB 권장. 인터넷 연결과 정상 NVIDIA 드라이버가 필요합니다.
- 모델과 도구는 고정된 버전·SHA256으로 검사합니다. 손상되었거나 호환되지 않는 설치는 정상 설치로 취급하지 않습니다.

## 기존 설치 재사용

저장소 상위 폴더의 `AI/ComfyUI_3D_1024`, `KimodoCpp/source`와 설치된 Blender를 검사합니다. 이 이름은 선택적 탐색 규칙이며 특정 사용자 경로를 요구하지 않습니다.

다른 위치를 재사용하려면 저장소 루트에 `local_config.json`을 만드세요. 이 파일은 Git에서 제외됩니다.

```json
{
  "existing_3d": "D:/AI/ComfyUI_3D_1024",
  "existing_cpp": "D:/AI/KimodoCpp/source",
  "blender": "D:/Blender/blender.exe"
}
```

정상 Python 환경·모델·Kimodo 런타임은 디렉터리 junction으로 연결합니다. 원본 Python과 시스템 Blender 환경을 변경하지 않습니다. ComfyUI 코드·입출력·작업 로그는 이 패키지의 runtime 안에 분리합니다. 재사용한 원본 폴더를 삭제하면 연결도 사용할 수 없으므로 보존해야 합니다.

기존 설치를 사용하지 않으려면 **비어 있는 별도 설치 폴더에서** `setup.bat -Fresh`를 실행하세요. 다른 PC에서는 기존 설치가 없어도 자동으로 새 환경을 만듭니다.

## 3D 생성

이미지 한 장 또는 같은 폴더의 `front.png`, `back.png`, `left.png`, `right.png` 네 장을 `generate_3d.bat`에 드래그합니다. 멀티뷰는 확장자를 제외한 이름이 정확히 front/back/left/right여야 하며 중복·누락 시 생성하지 않습니다.

형상 입력은 1024, 투영 텍스처 입력은 2048로 준비합니다. 2048 리사이징은 새로운 디테일을 추론하는 AI 초해상도가 아닙니다. 투영 방식의 뒷면·가려진 부위 품질에는 한계가 있습니다.

최종 결과는 입력 이미지 옆에 같은 이름의 GLB로 복사합니다. 멀티뷰는 front를 기준으로 하며, 이름 충돌 시 기존 파일을 덮어쓰지 않습니다. 자세한 보고서와 수정 가능한 Blend는 `runtime/ComfyUI_3D_1024/results`에 보관합니다. 최종 Blender 메시 정점 목표는 싱글 1000~1500, 멀티 2000~3000이며 GLB 정점은 UV 경계 때문에 더 많을 수 있습니다.

자동 시작한 ComfyUI는 완료·오류 후 종료합니다. 사용자가 먼저 실행한 서버는 종료하지 않습니다. 8189 포트가 다른 작업을 처리 중이라면 기다린 뒤 재실행하세요.

생성 완료 후 결과 폴더와 Blender를 자동으로 열고 `model_final.blend`를 로드합니다. 설치 시 선택한 시스템 Blender를 우선 사용하며, 사용할 수 없으면 내부 포터블 Blender를 사용합니다. 최종 모델을 선택해 화면에 맞추고 재질 미리보기로 표시합니다. 전용 애드온 설정도 유지되므로 열린 Blender에서 Kimodo를 사용할 수 있습니다. 새 모델의 모션 적용에는 리깅이 필요합니다. 자동 열기를 생략하려면 `--no-open` 옵션을 사용하세요.

Instant Meshes 결과가 형상 보존 검사에 실패하거나 실행이 120초를 넘기면 Blender에서 원본 기반 표면을 직접 감소시키는 대체 방식으로 한 번 재시도합니다. 대체 결과는 삼각형 위주이며 동일한 정점 예산과 형상 검사, 2048 재베이킹을 통과해야 저장됩니다. 두 방식 모두 실패하면 원본을 보존하고 오류로 중단합니다. 사용한 방식과 최초 형상 거절·타임아웃 사유는 `retopo_report.json`에 기록합니다.

## 리깅과 모션

3D 생성은 자동 리깅까지 수행하지 않습니다. 새 모델을 Mixamo 등에서 리깅하고 FBX로 가져온 후 Kimodo에서 적용합니다. 지원 대상은 Mixamo 기본 골격 또는 생성된 표준 Rigify 리그입니다. Mixamo Rig의 컨트롤 리그는 Rigify가 아니며 서로 바꿔 부르지 않습니다.

Blender의 N 패널 → Kimodo에서 CPP 백엔드를 사용하세요. 이 패키지는 공개 GGUF를 사용하는 Kimodo.cpp SOMA30 경로를 제공합니다. 로그인·대용량 Llama 캐시가 필요한 공식 Python/SOMA77 백엔드는 설치하지 않습니다.

SOMA30에 없는 상세 손가락 모션 대신 가벼운 기본 굽힘을 적용하고, 임시 수직 방향의 발가락 회전은 원래 대상 리그 자세로 보정합니다. 실제 손가락 모션이 있는 공식 SOMA77에는 이 보정을 적용하지 않습니다.

## 사용한 Git 저장소와 구성요소

이 프로젝트는 다음 외부 프로젝트를 조합하고, 설치·드래그앤드롭·후처리·Blender 연결을 위한 코드를 추가했습니다.

| 저장소 | 사용 목적 | 사용 버전 / 출처 |
|---|---|---|
| [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 3D 생성 워크플로 실행 서버 | 고정 커밋 `f1072eb0350638a3390ddb6afbcaa8c6b237c6fd` |
| [visualbruno/ComfyUI-Trellis2](https://github.com/visualbruno/ComfyUI-Trellis2) | TRELLIS.2 모델 로딩·3D 생성, Windows 네이티브 모듈, 텍스처 투영 코드 기반 | 고정 커밋 `b0e84c0f29857a444e8bcb5b9be2ea218e96efd0` |
| [wjakob/instant-meshes](https://github.com/wjakob/instant-meshes) | 생성 메시 리토폴로지 | 포함된 Windows 실행 파일의 SHA256을 검사; 소스 커밋은 별도 기록되지 않음 |
| [localai-org/kimodo.cpp](https://github.com/localai-org/kimodo.cpp) | Vulkan 기반 Kimodo SOMA30 모션 생성 | 고정 커밋 `5679ff19ba0a522c0b0516e9a9d402fe1af2c027`; Windows 경로 호환용 UTF-8 manifest 보정 |
| [tdw46/mixamo_blender4-main](https://github.com/tdw46/mixamo_blender4-main) | Blender에서 Mixamo 컨트롤 리그 생성 | 애드온 1.2.2 소스 포함; 소스 커밋은 별도 기록되지 않음 |
| [pypa/get-pip](https://github.com/pypa/get-pip) | 전용 Python 환경의 pip 초기 설치 | 고정 커밋 `f6f644156f23dfe9acc06e7b9ca75eee311f2e37` |

[PixelArtistry-Watertight-Meshes](https://github.com/pixelartistry/PixelArtistry-Watertight-Meshes)는 초기 구성 참고 프로젝트입니다. 해당 설치 프로그램을 포함하거나 그대로 실행하지 않으며, 이 저장소의 별도 1024 형상·2048 투영 텍스처 플로우를 사용합니다.

Blender와 Python은 공식 배포 파일을 사용합니다. Kimodo 리타게팅·SOMA30 손가락/발가락 보정 애드온은 이 저장소의 [addons/kimodo_rigify](addons/kimodo_rigify)에 있는 통합 코드입니다. 텍스처 투영 수정 코드는 [addons/comfyui-local-dual-resolution](addons/comfyui-local-dual-resolution)에 있으며 ComfyUI-Trellis2의 원저작권을 유지합니다.

다운로드 버전·파일 SHA256은 [manifests/software.json](manifests/software.json), Python 패키지는 [manifests/requirements-3d.lock](manifests/requirements-3d.lock)에 기록합니다. 모델 가중치는 Git에 포함하지 않고 Hugging Face에서 다운로드하며, 저장소·고정 revision·SHA256은 [manifests/models.json](manifests/models.json)을 기준으로 합니다. 모델별 공급처와 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 정리했습니다.

## 검증과 라이선스

`setup.bat`은 CUDA 연산, pip check, 네이티브 모듈, 모델·도구 경로, 격리된 Blender 애드온, SOMA30 리타게팅·발가락 보정과 Mixamo 컨트롤 리그 생성을 검사합니다. 전체 GPU 생성은 시간이 걸리므로 `run_generation_test.bat`으로 별도 실행합니다.

검증 범위는 [docs/VALIDATION.md](docs/VALIDATION.md), 외부 구성요소·라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요. 모델은 원 공급처에서 내려받으며 각 모델의 조건이 별도로 적용됩니다.
