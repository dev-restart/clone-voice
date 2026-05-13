# Clone Voice Studio

Clone Voice Studio는 음성 샘플 등록, TTS 음성 생성, STT 음성 인식, 스토리 오디오 제작, 보이스 체인저를 로컬에서 실행하는 웹 애플리케이션입니다.

## 폴더 구조

```text
backend/   FastAPI API 서버와 모델 연동 코드
frontend/  SvelteKit 웹 화면
```

## 필요 도구

- Python 3.12
- uv
- Node.js 22 이상 권장
- pnpm 10 이상
- ffmpeg

macOS 예시:

```bash
brew install uv node pnpm ffmpeg
```

## 설치

루트 디렉터리에서 실행합니다.

```bash
pnpm setup
```

위 명령은 backend 의존성 설치, frontend 의존성 설치, 기본 `.env` 파일 생성을 함께 처리합니다.

## 실행

```bash
pnpm dev
```

- Frontend: http://127.0.0.1:5174
- Backend: http://127.0.0.1:8000

## 모델 준비

대용량 모델은 저장소에 포함하지 않습니다. 필요한 모델만 선택해서 내려받습니다.

```bash
pnpm models
```

또는 필요한 항목만 실행할 수 있습니다.

```bash
./download-models.sh --tts
./download-models.sh --voxcpm --cosyvoice
./download-models.sh --seed-vc
```

모델 준비 후 `backend/.env`에서 사용할 모델을 `true`로 변경합니다.

```env
CLONE_VOICE_OMNIVOICE_ENABLED=true
CLONE_VOICE_VOXCPM_ENABLED=true
CLONE_VOICE_COSYVOICE_ENABLED=true
CLONE_VOICE_SEED_VC_ENABLED=true
```

## 개별 실행

Backend:

```bash
cd backend
uv sync
cp -n .env.example .env
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```bash
cd frontend
pnpm install
cp -n .env.example .env
pnpm run dev:5174
```

## 저장소에 포함하지 않는 항목

- 실제 `.env`
- 업로드 파일, 생성 음성, SQLite DB
- 모델 가중치와 vendor checkout
- `node_modules`, build 결과, cache 파일
- 테스트 코드와 내부 설명 문서
