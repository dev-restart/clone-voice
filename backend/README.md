# Clone Voice Studio Backend

FastAPI 기반 Backend입니다. 음성 자산, YouTube·Instagram media import, 생성 결과, model 상태, 장시간 작업 진행률을 REST와 WebSocket API로 제공합니다. 일반 사용자는 저장소 루트의 `pnpm start`를 사용하세요.

## 개발 실행

```bash
uv sync --locked --inexact
if [ ! -f .env ]; then cp .env.example .env; fi
uv run uvicorn main:app --host 127.0.0.1 --port 18109 --reload
```

상태 확인과 API 문서:

- Health: http://127.0.0.1:18109/api/health
- OpenAPI UI: http://127.0.0.1:18109/docs

## 주요 설정

설정은 `.env`에서 읽고 `CLONE_VOICE_` prefix를 사용합니다.

```env
CLONE_VOICE_STORAGE_DIR=storage
CLONE_VOICE_DATABASE_URL=
CLONE_VOICE_REGISTERED_MODELS=voxcpm,soulx-singer,stable-audio-sfx
CLONE_VOICE_DEFAULT_TTS_MODEL=voxcpm
CLONE_VOICE_DEFAULT_VC_MODEL=soulx-singer
CLONE_VOICE_WHISPER_MODEL=base
CLONE_VOICE_MEDIA_IMPORT_MAX_DURATION_SECONDS=3600
CLONE_VOICE_MEDIA_IMPORT_COOKIE_FILE=
```

모델별 활성화 값은 기본적으로 `false`입니다. 루트의 `download-models.sh`로 필요한 runtime을 설치한 다음 해당 모델만 활성화하세요.

`POST /api/audio/media-import`는 YouTube 단일 영상·Shorts와 Instagram 단일 게시물·Reel을 WAV로 저장합니다. 로그인 게시물용 cookie file은 저장소 밖에 두고 절대 경로만 `.env`에 지정하세요.

## 검증

```bash
uv run --extra dev pytest
```

Runtime 데이터와 model weight는 `storage/`, `vendor/`, `models/`, `pretrained_models/`에 저장되며 Git에 포함되지 않습니다.

대화 프로젝트는 기존 `studio_settings` 테이블의 `story-project:{id}` JSON에 저장합니다. `/api/story-studio/projects`와 `/{id}`는 목록·조회·저장을 제공하며, PUT의 `revision`이 현재 값과 다르면 409를 반환합니다. DELETE는 현재 revision을 query로 받고 프로젝트 metadata만 제거합니다. 생성 API의 `project_id`가 있으면 Backend가 완료 결과를 저장합니다. `/{id}/export?format=json|wav|mp3|txt|srt|zip`은 백업 또는 생성본을 내려받습니다.

텍스트 AI는 기본적으로 로컬 전용입니다. `GET /api/ai/providers`는 설치 모델과 key 존재 여부만 반환합니다. `PUT /api/ai/providers/connections`는 로컬 정책·endpoint·model·credentials를 저장하고, `POST /api/ai/providers/test`는 고정된 비민감 prompt로 응답을 확인합니다. `PUT /api/ai/providers/selection`으로 사용할 provider/model을 적용합니다. 연결 파일은 `ai_text_settings.json` 옆 `ai_text_connections.json`에 permission 0600으로 보관하며 key 값을 API 응답에 반환하지 않습니다. 상세 동작과 실제 검사는 [로컬 제작 검증](../docs/local-production-2026-09-30.md)을 참고하세요.
