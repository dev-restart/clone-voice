# 기여 안내

Clone Voice Studio는 한 사용자가 자신의 컴퓨터에서 실행하는 음성 제작 도구입니다. 기능 기여는 실제 사용자 흐름과 재현 가능한 검증을 함께 제안해 주세요.

## 개발 준비

Python 3.12, uv, Node.js 22 이상, pnpm 10, ffmpeg가 필요합니다. 지원 범위와 모델 설치는 [README](README.md)를 따릅니다.

```bash
pnpm run setup
pnpm dev
pnpm check
cd frontend
pnpm exec playwright install chromium
pnpm run test:e2e
```

브라우저 검사는 임시 SQLite/storage와 8011/5186 포트를 사용합니다. 실행 중인 사용자 서버와 저장 파일을 재사용하지 않습니다. CI는 모델 inference와 외부 provider를 실행하지 않으며, 실제 모델 검증은 별도로 기록합니다.

`pnpm run setup`의 `run`을 생략하지 않습니다. `pnpm setup`은 pnpm 자체의 shell 설정 명령입니다. 앱 설치는 lockfile을 확인하고 기존 optional runtime과 `.env`를 유지합니다.

공개 후보 파일 검사는 `pnpm check`와 CI에 포함됩니다. 실제 commit 후보를 stage한 뒤에는 아래 명령으로 Git index도 검사합니다. 이 검사는 staging이나 commit을 변경하지 않습니다.

```bash
python3 scripts/check_release.py
python3 scripts/check_release.py --staged
git diff --cached --check
```

runtime/media/credentials 경로, 10 MiB 초과 파일, 주요 token 형식을 검사하며 실제 값은 출력하지 않습니다. 완전한 secret 탐지나 라이선스 심사를 대신하지 않으므로 새 모델·dependency와 외부 자료는 별도로 검토합니다.

## 디자인 시스템, 번역, 모델

- UI 컴포넌트는 shadcn-svelte(`frontend/src/lib/components/ui`)를 기반으로 하며 `cd frontend && pnpm storybook`에서 확인합니다. 새 공용 컴포넌트에는 `src/stories`에 story를 함께 추가합니다.
- 화면 문구는 직접 쓰지 않고 `frontend/src/lib/i18n/messages/`의 ko/en 파일에 같은 키로 추가합니다. 한쪽만 추가하면 타입 검사가 실패합니다. 서버가 사용자에게 돌려주는 문장은 `tr("한국어", "English")`를 씁니다.
- 새 모델은 어댑터를 등록해 추가합니다. [모델 추가하기](docs/adding-a-model.md)를 따릅니다.
- 설치 스크립트를 바꾸면 `bash -n install.sh download-models.sh start.sh`(`make check-scripts`)를 실행합니다.

## 변경과 보고

버그 보고에는 OS·CPU/GPU, 재현 순서, 기대 동작, 실제 동작과 model ID를 포함합니다. token, cookie, 사적인 원문·녹음은 첨부하지 않습니다. 짧은 합성 음성이나 공개 가능한 테스트 자료로 재현해 주세요.

PR은 문제와 변경된 동작, 실행한 검사, 검증하지 못한 모델·환경을 설명합니다. 저장 계약을 바꿀 때는 기존 프로젝트 복구와 실패·충돌 경로를 함께 검증합니다. 모델이 없거나 꺼져 있어도 UI가 기능을 사용할 수 있다고 오인시키지 않아야 합니다. 스크린샷에는 허가받은 테스트 데이터만 포함합니다.

외부 dependency나 모델 runtime을 변경하면 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 upstream과 라이선스 경계를 반영합니다. model weight, `storage/`, `.env`, cookie, 계정 설정과 vendor checkout은 Git에 추가하지 않습니다.
