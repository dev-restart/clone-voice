# 외부 구성요소와 라이선스 경계

이 저장소에서 작성한 코드는 [MIT License](LICENSE)로 배포합니다. 이 라이선스는 외부 runtime, 모델 가중치, 가져온 미디어에 적용되지 않습니다. 아래는 주요 구성요소의 출처이며 전체 transitive dependency의 SBOM을 대신하지 않습니다. 설치 버전은 `backend/uv.lock`, `frontend/pnpm-lock.yaml`과 설치 script를 함께 확인합니다.

| 구성요소 | 용도 | upstream의 라이선스 구분 |
| --- | --- | --- |
| [VoxCPM / VoxCPM2](https://github.com/OpenBMB/VoxCPM) | TTS·voice cloning | code와 weights: Apache-2.0 |
| [OpenAI Whisper](https://github.com/openai/whisper#license) | 로컬 STT | code와 weights: MIT |
| [Ollama](https://github.com/ollama/ollama) / [Qwen3 4B](https://ollama.com/library/qwen3:4b) | 선택형 로컬 텍스트 AI | Ollama code: MIT. 예시 Qwen3 4B weights: Apache-2.0. 다른 선택 모델의 라이선스는 별도로 확인 |
| [SoulX-Singer](https://github.com/Soul-AILab/SoulX-Singer) | singing voice conversion | code와 weights: Apache-2.0. 현재 설치 script는 [SoulX-Singer-MLX](https://github.com/ailuntx/SoulX-Singer-MLX)와 mlx-community 변환 weights 및 전처리 모델도 사용하므로 각 배포물의 LICENSE/model card를 함께 확인 |
| [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) | MLX 효과음 생성 | code: MIT. weights: Stability AI Community License. code의 MIT와 같은 사용 조건이라고 취급하지 않음 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp#license) | 단일 영상 audio import | source/PyPI wheel: Unlicense. 공식 bundled executable은 포함 dependency에 따라 GPL-3.0+이며 EJS 등 추가 구성요소에는 별도 라이선스가 있음 |
| [shadcn-svelte](https://github.com/huntabyte/shadcn-svelte) · [Bits UI](https://github.com/huntabyte/bits-ui) · [Storybook](https://github.com/storybookjs/storybook) · [Lucide](https://github.com/lucide-icons/lucide) | 프런트엔드 UI 컴포넌트·디자인 시스템 문서·아이콘 | 대부분 MIT(Lucide는 ISC). 정확한 버전과 전체 목록은 `frontend/pnpm-lock.yaml`과 각 패키지의 LICENSE를 확인 |
| [FFmpeg](https://www.ffmpeg.org/legal.html) | 변환·normalize·오디오 결합 | 기본 LGPL-2.1-or-later, optional GPL 구성요소를 사용한 build는 GPL 조건 적용. 설치한 binary의 build configuration 확인 |

이 저장소는 model weights와 외부 checkout 또는 FFmpeg binary를 배포하지 않습니다. 사용자가 선택 기능 설치 script로 별도 다운로드합니다. 외부 소프트웨어나 가중치를 포함한 installer/container를 배포할 때는 해당 버전의 원문 라이선스·고지와 배포 조건을 별도로 보존해야 합니다.

목소리 사용 동의와 가져온 영상·음원의 권리는 코드 라이선스와 별도입니다. 샘플·데모 공개에는 본인 음성, 허가받은 음성 또는 합성 테스트 음성을 사용하고 생성물을 실제 인물의 발언으로 표시하지 않습니다.

확인 기준: 2026-09-30, 위 upstream 공식 README/라이선스 문서. 새 버전으로 설치하거나 재배포할 때는 설치된 배포물의 원문을 다시 확인합니다.
