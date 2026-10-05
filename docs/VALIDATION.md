# 설치 및 실행 검증

검증 장비: Windows x64 / RTX 3070 Ti 8GB / NVIDIA 드라이버 616.64 / RAM 약 32GB.

다른 물리 PC에서 검증한 것은 아닙니다. 같은 PC에서 기존 설치 재사용과 별도 공백·한글 경로의 새 Python·Blender 환경을 분리해 검사했습니다. 새 환경은 기존 Python 패키지를 연결하지 않았으며, 대용량 모델 파일만 SHA256 확인 후 재사용했습니다.

| 검사 | 내용 |
|---|---|
| 기존 설치 재사용 | 정상 Python·CUDA·모델 재사용, 기존 시스템 환경 보존 |
| 새 환경 | Python 3.12.10 및 고정 패키지 전체 설치, pip check |
| CUDA | 실제 matmul 및 새 캐시에서 Triton 커널 컴파일 |
| 다운로드 | 22개 고정 모델 URL 접근·크기 확인, 로컬 파일 SHA256 검사 |
| 다운로드 복구 | 중단 파일 Range 재개, 손상 파일 교체, 정상 파일 다운로드 생략 |
| 압축 해제 | 상위 경로 침범하는 ZIP 항목 차단 |
| Blender | 전용 설정 폴더, Kimodo/Mixamo Rig 로드, 컨트롤 리그 생성 |
| 모션 | 실제 Kimodo.cpp SOMA30 추론, Blender 리타게팅, 발가락 보정 |
| 재실행 | setup 재실행 시 정상 항목 생략, 모델 재다운로드 없음 |
| 한글 경로 | 내장 Python 경로 설정과 Windows CLI UTF-8 manifest 보정 |

기존 환경 경로의 실제 3D 생성은 1024 형상·2048 투영 텍스처·메시 정리·리토폴로지까지 완료했습니다. 샘플의 최종 Blender 메시 정점은 1252개이며, 결과 GLB는 examples/generated_3d.glb입니다. 별도 리깅 샘플에서 실제 60프레임 Kimodo 모션을 생성하고 적용했습니다.

새 Python·Blender 환경과 공백·한글 경로에서도 전체 3D 생성 및 실제 Kimodo.cpp 60프레임 생성 → Blender 적용이 통과했습니다. [fresh-generation-report.json](fresh-generation-report.json)에 범위를 기록했습니다. staged Git tree를 ZIP으로 추출한 패키지에서도 필수 런타임 해시와 설치 도구 테스트가 통과했습니다.

전체 테스트는 `run_generation_test.bat`, 설치 점검은 `verify.bat`으로 반복할 수 있습니다. 로그와 상세 결과는 각 설치의 `.state/`와 `runtime/ComfyUI_3D_1024/results/`에 저장됩니다.

**생성 성공과 메시 완성도는 다릅니다.** 샘플 리토폴로지에는 작은 경계 개구부가 남아 있어 수동 보수 검토가 필요합니다. 피부·손가락·옷과 관절의 변형 품질까지 자동 승인하지 않습니다. 멀티뷰는 정확한 front/back/left/right 파일명 검사를 사용하며, 입력과 사양에 따라 처리 시간이 달라집니다.
