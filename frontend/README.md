# Clone Voice Studio Frontend

SvelteKit 기반 Frontend입니다. 일반 사용자는 저장소 루트의 `pnpm start`를 사용하세요.

음성 등록과 Story Studio에서 YouTube·Instagram 주소를 입력하면 Backend가 저장한 WAV를 파형 선택 또는 local STT 입력으로 사용합니다.

## 개발 실행

```bash
pnpm install --frozen-lockfile
if [ ! -f .env ]; then cp .env.example .env; fi
pnpm run dev --host 127.0.0.1 --port 18185
```

```env
PUBLIC_API_BASE=http://127.0.0.1:18109
```

## Production build

```bash
pnpm run check
pnpm run build
HOST=127.0.0.1 PORT=18185 PUBLIC_API_BASE=http://127.0.0.1:18109 node build/index.js
```

`node_modules/`, `.svelte-kit/`, `build/`, Playwright 결과는 Git에 포함되지 않습니다.

## 제작 흐름 검증

```bash
pnpm run test:unit
pnpm exec playwright install chromium
pnpm run test:e2e
```

Playwright는 별도 임시 storage와 Backend 8011 / Frontend 5186 포트를 사용합니다. 2~4명 casting, 저장 실패·동시 편집 복구, 기존 browser 프로젝트 이관, 생성본 변경 경고와 다운로드, 주요 화면 및 모바일 레이아웃을 검사합니다. 설치된 Chromium을 별도로 사용할 때만 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`를 지정합니다.
