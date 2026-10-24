#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
# Uncommon default ports so they rarely collide with other dev servers (3000, 5173, 8000, 8080 ...).
BACKEND_PORT="${BACKEND_PORT:-18109}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-18185}"
PUBLIC_API_BASE="${PUBLIC_API_BASE:-http://127.0.0.1:$BACKEND_PORT}"
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://127.0.0.1:$FRONTEND_PORT}"

KILL_PORTS="${CLONE_VOICE_KILL_PORTS:-1}"     # 1: stop whatever holds our ports, 0: refuse to start
AUTO_MODELS="${CLONE_VOICE_AUTO_MODELS:-all}" # all: every supported model, core: voice + speech-to-text only, 0: none

BACKEND_PID=""
FRONTEND_PID=""

usage() {
	cat <<'USAGE'
Usage: ./start.sh [options]

  --no-kill      Do not stop programs that already use the ports; exit instead.
  --core-models  Download only the voice and speech-to-text models (skip song cover and sound effects).
  --no-models    Do not download missing models automatically.
  -h, --help     Show this help.

Environment: BACKEND_PORT (18109)  FRONTEND_PORT (18185)  BACKEND_HOST  FRONTEND_HOST  PUBLIC_API_BASE
USAGE
}

while (($#)); do
	case "$1" in
		--no-kill) KILL_PORTS=0 ;;
		--core-models) AUTO_MODELS=core ;;
		--no-models) AUTO_MODELS=0 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

# install.sh may have put uv or nvm-managed Node outside this shell's PATH.
load_toolchain() {
	export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
	export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
	if ! command -v node >/dev/null 2>&1 && [[ -s "$NVM_DIR/nvm.sh" ]]; then
		# shellcheck disable=SC1091
		. "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true
	fi
}
load_toolchain

require_command() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "필요한 명령을 찾을 수 없습니다 / Missing command: $1" >&2
		echo "먼저 ./install.sh 를 실행하세요. / Run ./install.sh first." >&2
		exit 1
	fi
}

probe_host() {
	case "$1" in
		0.0.0.0|::) echo "127.0.0.1" ;;
		*) echo "$1" ;;
	esac
}

port_is_open() {
	local host
	host="$(probe_host "$1")"
	python3 - "$host" "$2" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=0.2):
        raise SystemExit(0)
except OSError:
    raise SystemExit(1)
PY
}

listening_pids() {
	if command -v lsof >/dev/null 2>&1; then
		lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u
	elif command -v fuser >/dev/null 2>&1; then
		fuser -n tcp "$1" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true
	fi
}

# Stop whatever listens on the port so the app can start (Ctrl+C on a stale run, a crashed dev server ...).
ensure_port_available() {
	local host="$1" port="$2" label="$3" pid pids attempts
	port_is_open "$host" "$port" || return 0

	if [[ "$KILL_PORTS" != "1" ]]; then
		echo "$label 포트 $port가 이미 사용 중입니다. 해당 프로그램을 종료하거나 다른 포트를 지정하세요. / $label port $port is already in use." >&2
		exit 1
	fi
	pids="$(listening_pids "$port")"
	if [[ -z "$pids" ]]; then
		echo "$label 포트 $port를 쓰는 프로그램을 찾지 못했습니다. 직접 종료하거나 다른 포트를 지정하세요. / Could not find what uses port $port." >&2
		exit 1
	fi
	for pid in $pids; do
		echo "포트 $port를 쓰는 프로그램을 종료합니다 / Stopping the program on port $port: PID $pid ($(ps -p "$pid" -o command= 2>/dev/null | cut -c1-70))"
		kill -TERM "$pid" 2>/dev/null || true
	done
	for ((attempts = 0; attempts < 50; attempts++)); do
		port_is_open "$host" "$port" || return 0
		sleep 0.1
	done
	for pid in $pids; do kill -KILL "$pid" 2>/dev/null || true; done
	sleep 0.3
	if port_is_open "$host" "$port"; then
		echo "포트 $port를 비우지 못했습니다. 권한이 필요한 프로그램일 수 있습니다. / Could not free port $port." >&2
		exit 1
	fi
}

# Missing models are fetched into the project (backend/models, backend/vendor) on first run.
# Song cover and sound effects are Apple Silicon only; model_cache reports them only on that hardware.
ensure_models() {
	[[ "$AUTO_MODELS" != "0" ]] || return 0
	local missing scope="" flags=()
	[[ "$AUTO_MODELS" == "core" ]] && scope="core"
	missing="$(cd "$BACKEND_DIR" && uv run python -m app.model_cache missing $scope 2>/dev/null || true)"
	[[ -n "$missing" ]] || return 0

	case " $missing " in *" voxcpm "*|*" whisper "*) flags+=(--voxcpm --stt) ;; esac
	case " $missing " in *" soulx-singer "*) flags+=(--soulx-singer) ;; esac
	case " $missing " in *" stable-audio-sfx "*) flags+=(--sfx) ;; esac

	echo "필요한 모델이 없어 내려받습니다 ($missing). 처음 한 번만, 전체 약 10GB 이상이 필요할 수 있습니다."
	echo "Missing models ($missing): downloading once into this project. This can take 10 GB or more."
	if ! "$ROOT_DIR/download-models.sh" --yes ${flags[@]+"${flags[@]}"}; then
		echo "모델 설치에 실패했습니다. 앱은 계속 시작하며 설정 → 모델에서 상태를 확인할 수 있습니다. / Model setup failed; starting anyway." >&2
	fi
}

wait_for_port() {
	local host="$1"
	local port="$2"
	local label="$3"
	local pid="$4"
	local attempts=0

	while ! port_is_open "$host" "$port"; do
		if ! kill -0 "$pid" 2>/dev/null; then
			echo "${label}가 시작 중 종료됐습니다." >&2
			return 1
		fi
		if ((attempts >= 300)); then
			echo "${label}가 30초 안에 포트 $port를 열지 못했습니다." >&2
			return 1
		fi
		sleep 0.1
		attempts=$((attempts + 1))
	done
}

stop_child() {
	local pid="$1"
	if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
		return
	fi
	kill -TERM "$pid" 2>/dev/null || true
	wait "$pid" 2>/dev/null || true
}

cleanup() {
	trap - EXIT INT TERM HUP
	stop_child "$FRONTEND_PID"
	stop_child "$BACKEND_PID"
}

# A fresh clone only needs ./start.sh: missing tools, dependencies and .env are prepared here.
tools_missing=0
for tool in python3 uv pnpm node ffmpeg; do
	command -v "$tool" >/dev/null 2>&1 || tools_missing=1
done
if ((tools_missing)); then
	echo "필요한 도구가 없어 ./install.sh로 먼저 설치합니다. / Some tools are missing; running ./install.sh first."
	"$ROOT_DIR/install.sh" --models none --no-start
	load_toolchain
fi
require_command python3
require_command uv
require_command pnpm
require_command node

if [[ ! -d "$BACKEND_DIR" || ! -d "$FRONTEND_DIR" ]]; then
	echo "backend 또는 frontend 디렉터리를 찾을 수 없습니다." >&2
	exit 1
fi

if [[ ! -f "$BACKEND_DIR/.env" && -f "$BACKEND_DIR/.env.example" ]]; then
	cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
	echo "Frontend 의존성을 설치합니다. / Installing frontend dependencies."
	pnpm --dir "$FRONTEND_DIR" install --frozen-lockfile
fi

ensure_models

ensure_port_available "$BACKEND_HOST" "$BACKEND_PORT" "Backend"
ensure_port_available "$FRONTEND_HOST" "$FRONTEND_PORT" "Frontend"

if [[ ! -f "$FRONTEND_DIR/build/index.js" ]] || [[ -n "$(find "$FRONTEND_DIR/src" "$FRONTEND_DIR/static" "$FRONTEND_DIR/package.json" "$FRONTEND_DIR/svelte.config.js" "$FRONTEND_DIR/vite.config.ts" -newer "$FRONTEND_DIR/build/index.js" -print -quit 2>/dev/null)" ]]; then
	echo "Frontend production build를 준비합니다. / Building the frontend."
	pnpm --dir "$FRONTEND_DIR" run build
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

echo "Backend를 시작합니다: http://$BACKEND_HOST:$BACKEND_PORT"
(
	cd "$BACKEND_DIR"
	exec uv run uvicorn main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) &
BACKEND_PID=$!
wait_for_port "$BACKEND_HOST" "$BACKEND_PORT" "Backend" "$BACKEND_PID"

echo "Frontend를 시작합니다: http://$FRONTEND_HOST:$FRONTEND_PORT"
(
	cd "$FRONTEND_DIR"
	export HOST="$FRONTEND_HOST"
	export PORT="$FRONTEND_PORT"
	export ORIGIN="$FRONTEND_ORIGIN"
	export PUBLIC_API_BASE
	exec node build/index.js
) &
FRONTEND_PID=$!
wait_for_port "$FRONTEND_HOST" "$FRONTEND_PORT" "Frontend" "$FRONTEND_PID"

cat <<EOF

Clone Voice Studio가 실행됐습니다.
브라우저에서 http://$FRONTEND_HOST:$FRONTEND_PORT 를 여세요.
종료하려면 Ctrl+C를 누르세요.
EOF

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
	sleep 1
done
echo "Backend 또는 Frontend가 예기치 않게 종료됐습니다." >&2
exit 1
