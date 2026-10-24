# Clone Voice Studio 아키텍처

## 구성

```text
Browser (SvelteKit :18185)
  ├─ REST /api/*
  └─ WebSocket /api/ws/progress/{id}

FastAPI (:18109)
	├─ app/api/routes      기능별 API
	├─ app/services        model adapter, media import와 오디오 처리
  ├─ app/db              SQLAlchemy repository와 migration
  └─ storage             SQLite, 업로드, 생성 결과
```

Frontend는 `src/routes/+page.svelte`에서 공통 음성·콘텐츠·모델 상태와 workspace 전환을 관리합니다. 기능 UI는 `voice`, `tts`, `story`, `stt`, `conversion` component로 분리되고, API 주소와 WebSocket URL은 `src/lib/studio/api.ts`에서 조합합니다.

TTS 제작 설정과 발음 사전은 `ContentItem.production_settings`로 전달하며, 기존 `studio_settings` 테이블의 `content-production:{id}` JSON에 저장합니다. 같은 레코드에 결과별 `spoken_text`와 당시 설정 snapshot을 보관합니다. 기존 DB schema 변경 없이 이전 콘텐츠도 읽으며, 삭제된 결과의 metadata는 저장 시 함께 정리합니다. `GET /api/contents`는 설정 metadata를 한 번의 추가 query로 읽습니다.

`POST /api/tts/preview`는 대본 앞부분 최대 160자를 공통 TTS 경로에 전달합니다. 발음 alias 적용은 `services/pronunciation.py`, 화면 미리보기는 `studio/production.ts`가 담당합니다. 원문은 수정하지 않습니다. `GET /api/contents/{content_id}/results/{result_id}/export?format=wav|mp3|txt|zip`은 결과 snapshot으로 파일을 만듭니다. MP3와 ZIP은 임시 폴더를 사용하고 응답 후 정리합니다. 경로를 resolve한 뒤 outputs 내부인지 확인합니다.

Backend의 `app/main.py`는 기능별 router를 등록합니다. `app/config.py`는 `CLONE_VOICE_` 환경 변수를 읽고 runtime 저장 경로를 결정합니다. `app/services/model_router.py`는 모델별 차이를 공통 API 뒤에 숨기며, `CLONE_VOICE_REGISTERED_MODELS`에 등록한 모델만 `/api/models`에 노출합니다.

`app/services/media_import_service.py`는 허용된 YouTube·Instagram 단일 게시물 URL을 정규화한 뒤 `yt-dlp`와 `ffmpeg`로 audio만 WAV로 저장합니다. 가져온 파일은 일반 upload와 같은 storage 경계를 사용하고 voice 등록 또는 STT 입력으로 전달됩니다.

## 대화 프로젝트와 생성본

`StoryProjectStore`는 `studio_settings`의 `story-project:{id}` JSON을 사용합니다. schema migration 없이 프로젝트, 원문, 화자 casting, 번역문, 최신 생성본을 보관합니다. PUT은 revision에 대한 조건부 UPDATE로 오래된 화면의 덮어쓰기를 막습니다. 최초 DB 초기화는 process 내 lock으로 직렬화해 병렬 첫 요청이 같은 테이블을 생성하지 않도록 합니다.

Frontend는 변경본을 browser 임시 백업과 pending queue에 먼저 보관하고 PUT을 순차 전송합니다. 성공한 revision을 다음 변경에 사용하며, 409나 네트워크 실패 시 pending 편집을 유지합니다. 초기 로딩 시 서버 기록을 기준으로 기존 browser 전용 프로젝트를 이관하고, 충돌한 편집은 새 ID의 복구본으로 저장합니다. 초기 hydration 전 navigation 버튼은 비활성화해 클릭 누락을 막습니다.

생성 전에는 프로젝트 존재, 모든 단락의 adapter capability와 voice ID를 확인합니다. 생성 중 편집은 UI에서 잠그고 결과 저장 시 서버의 최신 편집본을 다시 읽어 보존합니다. 결과의 `source_segments`는 실제 읽은 대사와 합성 설정 snapshot입니다. 현재 편집본과 비교해 변경 여부를 표시하며 TXT/SRT는 항상 생성 당시 결과를 사용합니다. SFX와 쉼은 자막 시간에 포함되지만 효과음은 자막 대사에서 제외합니다.

JSON 복원은 새로운 ID를 부여하며 audio나 모델 가중치는 복사하지 않습니다. 프로젝트를 지워도 재사용 가능한 생성 파일을 삭제하지 않습니다. `파일 보관함`은 서버에 저장된 대담 결과를 직접 식별합니다.

## 장시간 작업

TTS, 스토리 오디오, 효과음, AI 커버는 `progress_id`를 요청에 포함합니다. Frontend는 `/api/ws/progress/{progress_id}`를 구독해 진행 상태를 표시합니다. 생성된 파일은 Backend가 관리하며 Frontend에는 `/api/files/...` URL만 전달합니다.

## 실행 mode

- `pnpm start`: Frontend production build + Uvicorn + adapter-node
- `pnpm dev`: Uvicorn reload + Vite hot reload
- Backend: `http://127.0.0.1:18109`
- Frontend: `http://127.0.0.1:18185`

Production 실행에서도 두 서버는 별도 port를 사용하므로 `PUBLIC_API_BASE`가 Backend 주소를 가리켜야 합니다.

## 저장소 경계

SQLite 기본 경로는 `backend/storage/clone_voice.db`입니다. 음성, 업로드, 생성 결과, 콘텐츠는 같은 storage 하위 directory를 사용하며 환경 변수로 각각 다른 disk에 배치할 수 있습니다. `.env`, runtime 데이터, model weight, 외부 repository checkout은 공개 source에 포함하지 않습니다.

## 기존 목소리와 로컬 텍스트 AI

루트 화면의 선택한 voice ID는 `clonevoice.preferredVoice.v1` browser 설정으로 보존합니다. 홈·라이브러리의 제작 바로가기가 TTS 새 대본, 대담 첫 화자, AI 커버 새 프로젝트로 전달합니다. 기존 프로젝트를 열 때에는 저장된 voice ID가 우선하며 새 기본값으로 덮어쓰지 않습니다. sample transcript 수정은 기존 voice PATCH API를 사용합니다.

AI 선택 파일은 provider/model만 저장하는 기존 `ai_text_settings.json` 계약을 유지합니다. 기존 `ai_text_connections.json`은 local-only 정책, 번역 모드와 이전 고정 연결·credentials를 permission 0600으로 유지합니다. 새로 등록하는 다중 API 연결과 키는 아래의 분리된 저장 계약을 사용합니다. 공개 catalog는 key 값 대신 `has_api_key`만 제공합니다. 기존 `providers` 목록을 유지하고 추가 API provider는 `api_providers`로 전달합니다.

`AiTextProviderService.complete`는 호출 전에 local-only 정책을 확인합니다. Ollama는 `/api/tags`와 `/api/show`에서 remote metadata를 확인한 뒤 로컬 모델에만 대본을 보냅니다. local dialogue/translation은 OpenAI-compatible `response_format`에 JSON schema를 전달하고 `finish_reason=length`는 명시적 오류로 처리합니다. 직접 쓴 대본의 음성 합성과 voice conversion은 텍스트 AI와 독립적으로 동작합니다. 외부 provider 선택은 명시적 opt-in이며 자동 fallback은 없습니다.

## 이름별 API 연결과 작업별 선택

`AiApiProfilesStore`는 선택 파일 옆 `ai_api_profiles.json`에 연결 목록과 작업별 routing을 저장합니다. 이름·프로토콜·기본 주소·인증 방식·모델 목록·제한을 가진 연결에는 `api-...` ID를 부여합니다. 전체 revision과 연결 revision을 비교해 오래된 편집을 409로 거절하며, 프로세스 lock과 원자적 파일 교체를 사용합니다. 한 로컬 Backend 프로세스를 기준으로 합니다.

이전 local/compatible/nvidia 설정은 최초 조회에서 읽기 전용으로 합성한 `api-legacy-...` 프로필로 표시합니다. 첫 저장 때 새 목록을 만들되 기존 설정 파일·키·선택은 보존합니다. 기존 연결을 편집한 새 프로필은 기본 또는 작업별 선택에 명시적으로 지정해야 적용됩니다. 단순 조회는 Keychain을 읽거나 인증을 이동하지 않습니다.

`ApiCredentialVault`는 Mac Security.framework/Keychain을 ctypes로 호출합니다. 키를 명령행 인자로 전달하지 않습니다. Keychain 사용 불가 시 파일 저장으로 자동 전환하지 않으며, 사용자가 선택한 private_file 모드만 별도 0700 디렉터리·0600 파일에 저장합니다. 파일은 암호화되지 않습니다. 프로필 JSON에는 보관 방식과 내부 참조만 저장하고 공개 응답에서는 참조도 제외합니다. 신규 키 저장 또는 메타데이터 저장 실패 시 새 키를 정리하며, 과거 키 정리 실패는 성공한 설정 저장과 구분해 경고합니다.

`AiApiClient`는 openai_chat, anthropic_messages, openai_responses를 별도 요청·응답 어댑터로 처리합니다. 설정한 인증 헤더를 사용하고 redirect는 따르지 않습니다. 원격 HTTP, URL userinfo/query/fragment, 허용되지 않은 추가 헤더를 거절합니다. 입력 문자 예산과 출력 토큰을 분리하며 Temperature는 선택값입니다. 출력 중단, 빈 응답, 거절·도구 출력은 적용하지 않습니다. 비스트리밍 텍스트만 다루며 이미지·실시간 음성·도구 실행은 범위 밖입니다.

연결별 1~4개 동시 요청과 최대 16개 대기를 프로세스 내에서 제한합니다. 대기열 슬롯 획득 후 최신 로컬 전용·사용 중지·삭제 상태를 다시 검사하므로 대기 중 정책 변경을 반영합니다. 이미 네트워크로 전송한 요청을 취소하거나 회수하는 기능은 아닙니다. 전용 로컬 Ollama 모드는 native metadata로 cloud/remote 모델을 차단합니다. 일반 localhost 호환 서버의 내부 중계 정책까지 확인하는 기능은 아닙니다.

`AiTextProviderService`의 task_selection은 translation/writing/sound_prompt 재정의를 우선하고 없으면 기존 기본 선택을 사용합니다. 번역의 Apple auto/apple 정책은 그보다 앞에서 적용합니다. 한 번역 요청에서 주소·프로필·키 snapshot을 고정하되 각 전송 전 최신 차단 정책을 검사합니다. 실패가 다른 제공처로의 재전송을 유발하지 않습니다. 기존 ChatGPT/Codex 및 Kimi CLI 경로는 유지합니다.

| API | 역할 |
| --- | --- |
| GET/POST /api/ai/connections | 공개 프로필 목록·연결 생성 |
| PUT/DELETE /api/ai/connections/{id} | revision 기반 수정·삭제 |
| POST /api/ai/connections/{id}/models | 저장한 연결의 모델 목록 조회 |
| POST /api/ai/connections/{id}/test | 고정 공개 예문의 텍스트 응답 검사 |
| PUT /api/ai/routing | 번역·대본·사운드 프롬프트 기본 연결 |
| PUT /api/ai/providers/selection | 기존 기본 선택 API, 새 프로필 ID도 수용 |

새 연결 및 기존 키 입력 API는 검증 오류에 키 입력값이 반영되지 않도록 처리합니다. Origin 검사는 local UI 범위를 보조하며 인증·다중 사용자 보안을 제공하는 것은 아닙니다. 서비스는 loopback에서 실행해야 합니다.

`AiModelManager`는 프리셋·수동 등록, 모델 조회·편집, revision 충돌, 명시적 삭제, 키 없는 설정 복사와 작업별 선택을 제공합니다. 키는 화면 메모리에만 두고 저장·닫기·화면 해제 때 비웁니다. 저장 실패/새로고침 때 편집은 유지하지만 탭 닫기 후 복구를 위해 키를 브라우저 저장소에 보관하지 않습니다. 연결 저장 성공 뒤 목록 갱신 실패는 저장 실패와 구분합니다. 응답 확인 표시는 이번 화면에서 테스트한 모델과 정확한 설정 revision에만 적용하며, 이후 페이지 로드에는 미검증으로 표시합니다.

## Apple 온디바이스 번역

`ai_text_connections.json`의 `translation_mode`는 `auto`, `apple`, `selected` 중 하나이며 기존 파일에 값이 없으면 `auto`를 사용합니다. 일반 대본 AI의 provider/model은 기존 선택 파일에 그대로 남습니다. 자동 모드는 Apple 준비 상태가 사용 가능할 때 `apple/apple-on-device`를 선택하며, 준비되지 않았을 때만 기존 선택과 local-only 정책을 적용합니다. 번역을 시작한 뒤에는 엔진을 고정하므로 추론 오류가 외부 호출로 이어지지 않습니다.

`AppleFoundationModelsService`는 프로젝트의 Swift FoundationModels 보조 프로그램으로 Mac 모델 상태와 text 생성을 요청합니다. 입력은 표준 입력의 JSON으로 전달하며 모델은 시스템 온디바이스 모델을 사용합니다. Python 기반 VoxCPM2·SoulX-Singer·Stable Audio 경로는 이 번역 서비스와 독립적입니다.

`OpenAICompatibleTranslator`는 기존 호출 계약을 유지하면서 Apple 또는 선택된 provider로 요청을 전달합니다. Apple은 1,000자, 다른 엔진은 2,400자 단위로 문장·문단 경계를 우선해 대본을 나눕니다. 조각 사이 공백과 치환 표시를 보존하며 각 대상 언어의 완성된 JSON 문자열을 확인한 뒤 결과를 반환합니다. 대상 언어 누락, 비어 있는 값, 중복 키, 잘린 JSON, 치환 표시 변경은 오류입니다. 한 요청은 최대 8개 언어·64회 생성으로 제한합니다.

`GET /api/ai/providers`의 `translation`에는 저장 모드, 실제 선택될 provider/model과 Apple 준비 상태가 포함됩니다. `PUT /api/ai/providers/connections`에서 `translation_mode`를 저장하고, `POST /api/ai/translation/test`는 고정된 공개 한국어 문장을 영어로 번역해 결과와 소요 시간을 반환합니다. 화면 진입과 상태 새로고침은 text 생성을 실행하지 않습니다.

## 음성 등록의 구간 분석

VoiceCreateEditor는 소스 revision, 선택 범위 키와 대본 revision을 함께 관리한다. 소스 교체 시 이전 분석·전사 요청을 취소하고, 선택 전사 중 범위·입력이 바뀌면 늦은 응답을 적용하지 않는다. 대본과 범위가 일치해야 해당 대본으로 등록할 수 있다.

전체 위치 파형과 확대 파형은 같은 WaveSurfer 오디오를 사용한다. 추천 미리듣기와 구간 선택을 분리하고, 숫자 입력·파형 핸들·문장 선택은 한 범위를 갱신한다. 서버에서 가져온 오디오 URL은 재사용하며 로컬 파일은 분석용 업로드를 공유한다.

POST /api/audio/sample-analysis는 앱 uploads 내부의 512MB·60분 이하 파일을 받아 16kHz mono로 변환한 뒤 SoundAnalysis 내장 speech/music/singing과 음량·침묵·클리핑으로 후보를 계산한다. Swift helper는 별도의 LLM 서버와 FoundationModels 상태를 사용하지 않는다. native 실패 시 음량 기반 결과임을 명시한다. 분석은 프로세스당 한 건이고 성공 결과를 파일 식별 정보와 알고리즘 버전으로 캐시한다.

POST /api/audio/sample-transcript는 같은 서버 파일의 최대 30초 창을 기존 Whisper/Apple Speech로 전사하고 전체 파일 좌표를 한 번 적용한다. 범위 밖·비유한 시간은 선택 가능한 대본으로 반환하지 않으며 임시 조각을 정리한다. 짧은 음성 위치 탐색과 5~8초 추천을 구분하고, 단일 화자나 복제 품질 보장은 제공하지 않는다.

## 작업 기본값과 메뉴

`studio-preferences:v1` JSON은 시작 메뉴(tts/sfx/changer/home), 원본 기본 언어, 받아쓰기 제공자, 보조 메뉴 표시 여부를 보관합니다. `GET/PUT /api/studio/preferences`는 허용된 값만 읽고 저장합니다. 기본 메뉴는 목소리 클론·사운드 만들기·노래 커버이며 대화 오디오와 독립 받아쓰기는 설정에서 표시합니다.

루트는 초기 데이터와 기본 설정을 모두 읽은 뒤 메뉴를 활성화합니다. 모바일 메뉴는 메뉴 ID를 key로 사용해 비동기 설정으로 보조 메뉴가 추가될 때 다른 항목의 버튼을 재사용하지 않습니다. 시작 메뉴 응답이 늦더라도 이미 시작한 화면 이동을 되돌리지 않습니다.

`StudioPreferencesPanel`은 작업 기본값과 번역 방식 저장을 분리합니다. 번역 모드 PUT은 `translation_mode`만 전송합니다. 기존 AI 연결 편집기는 고급 설정 안에 있고 중복 번역 컨트롤은 숨깁니다. Apple 받아쓰기 기본 선택과 운영체제 정보는 실제 전사 성공 판정이 아닙니다. 루트가 저장된 `stt_provider`를 목소리 등록, 독립 받아쓰기, 대화의 미디어 원문 가져오기, 노래 커버의 가사 인식에 전달합니다. 개별 화면의 사용자가 바꾼 제공자는 해당 화면의 후속 작업에서 유지합니다.

## 언어별 음성 대기열

`ContentItem.source_language`를 기존 콘텐츠 제작 메타데이터에 저장합니다. 이전 데이터는 저장된 제작 언어 또는 한국어를 사용합니다. 원본 작성, 언어별 번역 편집, 음성 생성 대기열을 분리하며 직접 입력한 번역은 명시적 덮어쓰기 없이 보존합니다. 번역 자체의 오류가 수동 편집과 음성 생성을 막지 않습니다.

| API | 역할 |
| --- | --- |
| GET /api/contents/{id} | 최신 대본과 결과 재조회 |
| POST /api/contents/{id}/jobs | 언어별 음성 접수, 202와 작업 목록 반환 |
| GET /api/generation-jobs?content_id=... | 대기열 조회 |
| POST /api/generation-jobs/{id}/cancel | 대기 중 취소 |
| POST /api/generation-jobs/{id}/retry | 실패·취소된 접수의 동일 대본으로 새 작업 생성 |

`GenerationQueue`는 DB URL별 프로세스 singleton, 작업당 `tts-job:{id}` 행과 한 개 worker를 사용합니다. 언어별 작업은 최대 32개까지 활성 상태로 접수하며 모델 추론은 한 번에 하나입니다. 동일 batch ID와 동일 요청은 기존 작업을 반환하고, 다른 대본으로 ID를 재사용하면 409입니다. 언어별 실제 대본, 목소리 프로필, 발음 규칙과 생성 설정은 접수 시 복사하며 상태 API에는 공개 필드만 반환합니다.

`generation_gate.py`는 콘텐츠 TTS, 직접 TTS와 미리 듣기 추론이 겹치지 않게 직렬화합니다. 대화 전체 생성·사운드·커버의 기존 처리 API를 모두 포괄하는 공용 GPU 스케줄러는 아닙니다. 하나의 DB에는 하나의 로컬 Backend 프로세스를 사용해야 합니다.

생성 helper는 최신 콘텐츠에 결과만 추가합니다. `ContentStore.patch`, `append_results`, `remove_result`는 process lock과 최신 조회로 진행 중 편집·다른 결과를 보존합니다. 생성 결과 ID는 작업 ID와 언어로 결정되므로 중복 append를 막습니다. 삭제된 콘텐츠나 목소리를 완료·재시도 시 되살리지 않습니다.

모델 실행 오류와 완료 상태 저장 오류를 분리합니다. 이미 결과가 만들어졌으면 모델을 다시 호출하지 않고 완료 기록 저장만 재시도합니다. 서버 재시작 또는 실패 재시도 전 저장된 결과를 조회해 이전 작업을 복구합니다. 결과 조회 자체가 실패하면 원래 오류를 보존하고 중복 생성을 방지하도록 재시도를 409로 막습니다. 결과가 없는 재시작 중단 기록은 실패로 표시하며 자동 실행하지 않습니다.

Frontend는 콘텐츠 대기열을 주기적으로 조회하고, 결과를 갱신해도 편집 중인 글은 유지합니다. 공통 상태 표시가 화면 이동 후 진행과 완료를 보여주며 해당 대본을 다시 열 수 있습니다. 대본을 수정한 뒤에도 기존 음원의 재생·내보내기는 생성 당시 글과 설정을 기준으로 합니다.

## 사운드 프로젝트·에셋·버전

`SoundProjectStore`는 `sound-project:{id}` JSON에 프로젝트와 에셋, 버전 기록을 저장합니다. 프로젝트별 최대 300개 에셋, 에셋별 최대 100개 결과를 보관합니다. PUT/DELETE는 revision을 비교하며 저장된 버전의 원문·경로·seed 등 결과 메타데이터를 임의 변경하지 못하게 검증합니다. 새 음원 URL은 outputs의 안전한 basename으로 제한합니다.

| API | 역할 |
| --- | --- |
| GET /api/sound-projects | 프로젝트 목록 |
| GET/PUT/DELETE /api/sound-projects/{id} | 프로젝트 조회·저장·삭제 |
| GET /api/sound-projects/{id}/export | JSON 프로젝트 백업 |
| POST /api/sound-effects/generate | 선택적으로 project_id와 asset_id를 받아 해당 에셋에 결과 추가 |

생성 요청은 프로젝트와 에셋이 존재하는지 먼저 확인합니다. 완료 뒤 최신 revision에 결과를 추가하여 진행 중 편집을 보존합니다. 여러 변형 중 일부만 생성되면 성공 결과와 `generation_warning`을 반환하고, 음원 생성 후 목록 저장이 실패하면 `storage_warning`과 재생 가능한 결과를 반환합니다. 이 경우 사용자에게 재생성을 요구하지 않습니다.

Frontend는 에셋 편집을 저장한 후 생성합니다. 게임 UI·영상 전환·환경음 3개 묶음의 12개 예시에는 편집 가능한 프롬프트만 포함합니다. 생성 버전별 원문, 실제 생성 프롬프트, 제외 요소와 seed를 확인하고 재생·다운로드할 수 있습니다. 비슷하게 만들기는 새 에셋에 설정을 복사하며 기존 음원을 새 결과로 복제하지 않습니다.

저장 충돌은 서버 기준본·로컬 변경·최신 서버 변경을 비교해 처리하고, 충돌한 필드와 저장 실패 편집은 브라우저 복구 데이터에 유지합니다. 목록에 연결하지 못한 완료 음원도 별도로 보관합니다. 과거 브라우저 효과음 기록의 이관은 안정적인 ID를 사용하고 원본 기록을 보존합니다. 프로젝트·에셋·버전 삭제는 메타데이터를 제거하며 실제 음원 파일은 남깁니다.


## 모델 영역과 어댑터

모델은 **영역(domain)**으로 묶습니다: 음성(`voice`), 음악(`music`), 커버(`cover`), 효과음(`sfx`). 어댑터가 선언한 capability(`tts`, `music_generation`, `voice_conversion`, `sound_effect_generation`)가 어느 영역에 나타날지 결정하며, 한 모델이 여러 영역에 나타날 수 있습니다.

- `@register_adapter`로 `ADAPTER_REGISTRY`에 등록하고 `CLONE_VOICE_REGISTERED_MODELS`에 id를 넣으면 `ModelRouter`가 생성합니다. 알 수 없는 id는 경고 후 무시합니다.
- 기본 모델은 영역별로 `default_models`에 저장합니다(`default_tts_model`, `default_vc_model`은 호환용). 음성·커버는 필수 영역으로 최소 한 개가 켜져 있어야 하고 음악·효과음은 선택입니다.
- 프런트엔드는 `models.ts`의 순수 규칙과 `ModelPicker`/`ModelCard`/`ModelDomainSection`으로 모든 작업 화면에서 같은 선택 UI를 씁니다.
- 새 어댑터 작성 순서는 [모델 추가하기](adding-a-model.md)에 있습니다.

## 표시 언어

프런트엔드는 한국어/영어 메시지 파일을 `frontend/src/lib/i18n/messages/`에 두고 같은 키 구조를 타입으로 강제합니다. 선택한 언어는 브라우저에 저장하며 기본은 한국어입니다. 모든 API 요청은 `Accept-Language`를 보내고, 서버는 요청 단위 locale(ContextVar)로 `tr(ko, en)` 메시지를 고릅니다. 생성 대기열 작업은 요청 당시의 locale 컨텍스트를 복사해 실행하므로 진행 메시지도 같은 언어로 나옵니다. 샘플 분석 캐시 키에도 locale이 포함됩니다.

## 링크 가져오기

`media_import_service`는 `yt-dlp`로 YouTube·Instagram 단일 게시물을 오디오 WAV로 가져옵니다. `inspect_media`가 다운로드 없이 제목과 길이를 돌려주고(`POST /api/audio/media-info`), 가져오기는 선택적 시작·끝 구간만 `download_range_func`로 받습니다. 길이 한도(`media_import_max_duration_seconds`)는 구간을 지정하면 구간 길이에 적용됩니다.
