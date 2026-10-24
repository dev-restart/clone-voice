#!/usr/bin/env bash
# Clone Voice Studio installer for macOS and Linux (Windows: WSL 2).
#
#   ./install.sh                 interactive install, then offers to start the app
#   ./install.sh -y              accept the recommended defaults without prompting
#   ./install.sh --models all    also install voice cover and sound-effect models
#   curl -fsSL https://raw.githubusercontent.com/dev-restart/clone-voice/main/install.sh | bash
#
# It installs only what is missing: system packages, uv, Python 3.12, Node.js 22+,
# pnpm, backend/frontend dependencies, and the model weights you choose.
set -Eeuo pipefail

REPO_URL="${CLONE_VOICE_REPO:-https://github.com/dev-restart/clone-voice.git}"
INSTALL_HOME="${CLONE_VOICE_HOME:-$HOME/clone-voice}"
NODE_MAJOR_REQUIRED=22
PNPM_VERSION="10.33.0"
NVM_VERSION="v0.40.4"

ASSUME_YES=0
MODELS=""           # empty = ask; "none" = skip; comma list of tts,stt,cover,sfx; or "all"
START_AFTER=ask     # ask | yes | no
LANG_UI=""

# ---------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then
	BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
	BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

detect_lang() {
	if [[ -n "$LANG_UI" ]]; then return; fi
	case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
		ko*) LANG_UI=ko ;;
		*) LANG_UI=en ;;
	esac
}

# msg "한국어" "English"
msg() { if [[ "$LANG_UI" == ko ]]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
step() { printf '\n%s==>%s %s%s%s\n' "$GREEN" "$RESET" "$BOLD" "$(msg "$1" "$2")" "$RESET"; }
info() { printf '    %s\n' "$(msg "$1" "$2")"; }
warn() { printf '%s    ! %s%s\n' "$YELLOW" "$(msg "$1" "$2")" "$RESET" >&2; }
die() { printf '%s오류/Error: %s%s\n' "$RED" "$(msg "$1" "$2")" "$RESET" >&2; exit 1; }

on_error() {
	local code=$?
	printf '\n%s%s%s\n' "$RED" "$(msg "설치가 중간에 멈췄습니다 (종료 코드 $code). 위 메시지를 확인한 뒤 ./install.sh 를 다시 실행하면 이어서 진행합니다." "Installation stopped (exit code $code). Fix the message above and rerun ./install.sh; finished steps are skipped.")" "$RESET" >&2
	exit "$code"
}
trap on_error ERR

have() { command -v "$1" >/dev/null 2>&1; }

# Prompts read from the terminal even when the script itself is piped from curl.
ask_yes_no() { # ask_yes_no "한국어" "English" default(y|n)
	local default="${3:-y}" reply hint
	if ((ASSUME_YES)); then [[ "$default" == y ]]; return; fi
	if [[ ! -r /dev/tty ]]; then [[ "$default" == y ]]; return; fi
	if [[ "$default" == y ]]; then hint="[Y/n]"; else hint="[y/N]"; fi
	printf '%s %s ' "$(msg "$1" "$2")" "$hint" >/dev/tty
	read -r reply </dev/tty || reply=""
	reply="${reply:-$default}"
	[[ "$reply" == [yY]* ]]
}

usage() {
	cat <<'USAGE'
Usage: ./install.sh [options]

  -y, --yes            Accept defaults and skip every confirmation.
  --models LIST        Models to install: tts,stt,cover,sfx | all | none
                       (default: ask; recommended is tts,stt)
  --start / --no-start Start the app when installation finishes (default: ask).
  --lang ko|en         Message language (default: from your locale).
  -h, --help           Show this help.

Environment:
  CLONE_VOICE_HOME     Where to clone when run through curl (default: ~/clone-voice)
  CLONE_VOICE_REPO     Git URL to clone from.
USAGE
}

while (($#)); do
	case "$1" in
		-y|--yes) ASSUME_YES=1 ;;
		--models) MODELS="${2:?--models needs a value}"; shift ;;
		--models=*) MODELS="${1#*=}" ;;
		--start) START_AFTER=yes ;;
		--no-start) START_AFTER=no ;;
		--lang) LANG_UI="${2:?--lang needs ko or en}"; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done
detect_lang

# ---------------------------------------------------------------- platform
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
	Darwin|Linux) ;;
	MINGW*|MSYS*|CYGWIN*) die "Windows에서는 WSL 2 (Ubuntu) 안에서 실행해 주세요: wsl --install -d Ubuntu" "On Windows, run this inside WSL 2 (Ubuntu): wsl --install -d Ubuntu" ;;
	*) die "지원하지 않는 운영체제입니다: $OS" "Unsupported operating system: $OS" ;;
esac
APPLE_SILICON=0
if [[ "$OS" == Darwin && "$ARCH" == arm64 ]]; then APPLE_SILICON=1; fi

SUDO=""
if [[ "$(id -u)" != 0 ]] && have sudo; then SUDO="sudo"; fi

# ---------------------------------------------------------------- locate or fetch the repo
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
ROOT_DIR=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
	candidate="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
	if [[ -d "$candidate/backend" && -d "$candidate/frontend" ]]; then ROOT_DIR="$candidate"; fi
fi

if [[ -z "$ROOT_DIR" ]]; then
	step "저장소를 내려받습니다" "Fetching the repository"
	if ! have git; then
		case "$OS" in
			Darwin) xcode-select --install 2>/dev/null || true; die "Xcode Command Line Tools 설치가 끝난 뒤 다시 실행해 주세요." "Finish installing the Xcode Command Line Tools, then rerun." ;;
			*) if have apt-get; then $SUDO apt-get update -y && $SUDO apt-get install -y git curl
			   elif have dnf; then $SUDO dnf install -y git curl
			   elif have pacman; then $SUDO pacman -Sy --noconfirm git curl
			   else die "git을 먼저 설치해 주세요." "Please install git first."; fi ;;
		esac
	fi
	if [[ -d "$INSTALL_HOME/.git" ]]; then
		info "이미 있는 저장소를 갱신합니다: $INSTALL_HOME" "Updating existing checkout: $INSTALL_HOME"
		git -C "$INSTALL_HOME" pull --ff-only
	else
		git clone --depth 1 "$REPO_URL" "$INSTALL_HOME"
	fi
	args=()
	((ASSUME_YES)) && args+=(--yes)
	[[ -n "$MODELS" ]] && args+=(--models "$MODELS")
	[[ "$START_AFTER" == yes ]] && args+=(--start)
	[[ "$START_AFTER" == no ]] && args+=(--no-start)
	args+=(--lang "$LANG_UI")
	exec bash "$INSTALL_HOME/install.sh" "${args[@]}"
fi

BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
cd "$ROOT_DIR"

printf '\n%s%s%s\n' "$BOLD" "Clone Voice Studio" "$RESET"
info "내 컴퓨터에서 목소리 클론·음악 커버·효과음을 만드는 오프라인 스튜디오를 설치합니다." "Installing the offline studio for voice cloning, song covers and sound effects."
info "플랫폼: $OS/$ARCH" "Platform: $OS/$ARCH"

# ---------------------------------------------------------------- toolchain
install_system_packages() {
	local missing=()
	have git || missing+=(git)
	have curl || missing+=(curl)
	have ffmpeg || missing+=(ffmpeg)
	if ((${#missing[@]} == 0)) && { [[ "$OS" == Darwin ]] || have gcc; }; then
		info "시스템 도구 확인 완료 (git, curl, ffmpeg)" "System tools present (git, curl, ffmpeg)"
		return
	fi
	if [[ "$OS" == Darwin ]]; then
		if ! have brew; then
			warn "Homebrew가 없습니다." "Homebrew is not installed."
			ask_yes_no "Homebrew를 설치할까요?" "Install Homebrew?" y || die "Homebrew 없이는 ffmpeg 설치를 진행할 수 없습니다." "Cannot install ffmpeg without Homebrew."
			/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
			if [[ -x /opt/homebrew/bin/brew ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; elif [[ -x /usr/local/bin/brew ]]; then eval "$(/usr/local/bin/brew shellenv)"; fi
		fi
		if ((${#missing[@]})); then brew install "${missing[@]}"; fi
	elif have apt-get; then
		$SUDO apt-get update -y
		$SUDO apt-get install -y git curl ffmpeg build-essential ca-certificates
	elif have dnf; then
		$SUDO dnf install -y git curl ffmpeg-free gcc gcc-c++ make
	elif have pacman; then
		$SUDO pacman -Sy --noconfirm git curl ffmpeg base-devel
	else
		die "패키지 관리자를 찾지 못했습니다. git, curl, ffmpeg를 직접 설치한 뒤 다시 실행해 주세요." "No supported package manager found. Install git, curl and ffmpeg manually, then rerun."
	fi
}

install_uv() {
	export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
	if have uv; then info "uv $(uv --version | awk '{print $2}')" "uv $(uv --version | awk '{print $2}')"; return; fi
	curl -LsSf https://astral.sh/uv/install.sh | sh
	export PATH="$HOME/.local/bin:$PATH"
	have uv || die "uv 설치 후에도 명령을 찾을 수 없습니다." "uv was installed but is not on PATH."
}

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

load_nvm() {
	export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
	# shellcheck disable=SC1091
	[[ -s "$NVM_DIR/nvm.sh" ]] && . "$NVM_DIR/nvm.sh"
	return 0
}

install_node() {
	load_nvm
	if have node && (( $(node_major) >= NODE_MAJOR_REQUIRED )); then
		info "Node.js $(node -v)" "Node.js $(node -v)"
		return
	fi
	if [[ "$OS" == Darwin ]] && have brew; then
		brew install node@22 || brew install node
		if [[ -d "$(brew --prefix)/opt/node@22/bin" ]]; then export PATH="$(brew --prefix)/opt/node@22/bin:$PATH"; fi
	else
		curl -fsSo- "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh" | PROFILE=/dev/null bash
		load_nvm
		nvm install "$NODE_MAJOR_REQUIRED"
		nvm use "$NODE_MAJOR_REQUIRED"
	fi
	have node && (( $(node_major) >= NODE_MAJOR_REQUIRED )) || die "Node.js $NODE_MAJOR_REQUIRED 이상을 준비하지 못했습니다." "Could not provide Node.js $NODE_MAJOR_REQUIRED or newer."
}

install_pnpm() {
	if have pnpm; then info "pnpm $(pnpm -v)" "pnpm $(pnpm -v)"; return; fi
	if have corepack; then
		corepack enable 2>/dev/null || true
		corepack prepare "pnpm@$PNPM_VERSION" --activate 2>/dev/null || true
	fi
	have pnpm || npm install -g "pnpm@$PNPM_VERSION"
	have pnpm || die "pnpm을 설치하지 못했습니다." "Could not install pnpm."
}

step "1/5  필요한 도구 확인·설치" "1/5  Checking and installing tools"
install_system_packages
install_uv
info "Python 3.12 (uv)" "Python 3.12 (via uv)"
uv python install 3.12
install_node
install_pnpm

# ---------------------------------------------------------------- model selection
want_model() { [[ ",$MODELS," == *",$1,"* ]]; }

choose_models() {
	if [[ -n "$MODELS" ]]; then
		[[ "$MODELS" == all ]] && MODELS="tts,stt,cover,sfx"
		[[ "$MODELS" == none ]] && MODELS=""
		return
	fi
	local recommended="tts,stt"
	if ((ASSUME_YES)) || [[ ! -r /dev/tty ]]; then MODELS="$recommended"; return; fi

	{
		printf '\n%s\n' "$(msg "설치할 모델을 고르세요. 모델은 이 컴퓨터에 내려받아 인터넷 없이 실행합니다." "Choose the models to install. They are downloaded once and run offline on this computer.")"
		printf '  1) %s\n' "$(msg "음성 생성·목소리 복제 — VoxCPM2 (수 GB, 권장)" "Voice generation & cloning — VoxCPM2 (several GB, recommended)")"
		printf '  2) %s\n' "$(msg "받아쓰기 — Whisper base (약 150MB, 권장)" "Speech-to-text — Whisper base (~150 MB, recommended)")"
		if ((APPLE_SILICON)); then
			printf '  3) %s\n' "$(msg "노래 커버 — SoulX-Singer (수 GB)" "Song cover — SoulX-Singer (several GB)")"
			printf '  4) %s\n' "$(msg "효과음 — Stable Audio Small-SFX (수 GB)" "Sound effects — Stable Audio Small-SFX (several GB)")"
		else
			printf '  %s\n' "$(msg "(노래 커버·효과음 모델은 현재 Apple Silicon Mac 전용입니다)" "(Song cover and sound-effect models currently require an Apple Silicon Mac)")"
		fi
		printf '%s ' "$(msg "번호를 쉼표로 입력 [기본 1,2 / a=전체 / n=없음]:" "Numbers separated by commas [default 1,2 / a=all / n=none]:")"
	} >/dev/tty
	local reply
	read -r reply </dev/tty || reply=""
	reply="${reply:-1,2}"
	case "$reply" in
		a|A|all) MODELS="tts,stt,cover,sfx" ;;
		n|N|none) MODELS="" ;;
		*)
			MODELS=""
			IFS=',' read -ra picks <<<"$reply"
			for pick in "${picks[@]}"; do
				case "${pick// /}" in
					1) MODELS+="tts," ;; 2) MODELS+="stt," ;; 3) MODELS+="cover," ;; 4) MODELS+="sfx," ;;
				esac
			done
			MODELS="${MODELS%,}"
			;;
	esac
}

choose_models
if ((APPLE_SILICON == 0)); then
	if want_model cover || want_model sfx; then
		warn "노래 커버·효과음 모델은 Apple Silicon 전용이라 건너뜁니다." "Skipping cover/sound-effect models: Apple Silicon only."
		MODELS="$(printf '%s' "$MODELS" | tr ',' '\n' | grep -vE '^(cover|sfx)$' | paste -sd, - || true)"
	fi
fi

# ---------------------------------------------------------------- dependencies
step "2/5  백엔드 의존성 (uv)" "2/5  Backend dependencies (uv)"
sync_args=(sync --locked --inexact)
want_model tts && sync_args+=(--extra voxcpm)
(cd "$BACKEND_DIR" && uv "${sync_args[@]}")
[[ -f "$BACKEND_DIR/.env" ]] || cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
if want_model tts && [[ "$OS" == Darwin ]]; then
	(cd "$BACKEND_DIR" && ./scripts/patch_torchcodec_macos.sh)
fi

step "3/5  프론트엔드 의존성 (pnpm)" "3/5  Frontend dependencies (pnpm)"
(cd "$FRONTEND_DIR" && pnpm install --frozen-lockfile)
[[ -f "$FRONTEND_DIR/.env" ]] || cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"

# ---------------------------------------------------------------- models
step "4/5  모델 내려받기" "4/5  Downloading models"
if [[ -z "$MODELS" ]]; then
	info "선택한 모델이 없습니다. 나중에 ./download-models.sh 로 추가할 수 있습니다." "No models selected. Add them later with ./download-models.sh."
else
	info "대상: $MODELS" "Selected: $MODELS"
	model_args=(--yes --no-deps)
	want_model tts && model_args+=(--voxcpm)
	want_model stt && model_args+=(--stt)
	want_model cover && model_args+=(--soulx-singer)
	want_model sfx && model_args+=(--sfx)
	"$ROOT_DIR/download-models.sh" "${model_args[@]}"
fi

step "5/5  앱 빌드" "5/5  Building the app"
(cd "$FRONTEND_DIR" && pnpm run build)

printf '\n%s%s%s\n' "$GREEN$BOLD" "$(msg "설치가 끝났습니다." "Installation complete.")" "$RESET"
info "실행:  ./start.sh   (또는 pnpm start)" "Run:  ./start.sh   (or pnpm start)"
info "주소:  http://127.0.0.1:18185" "Open:  http://127.0.0.1:18185"

case "$START_AFTER" in
	yes) exec "$ROOT_DIR/start.sh" ;;
	no) ;;
	*) if ask_yes_no "지금 바로 실행할까요?" "Start Clone Voice Studio now?" y; then exec "$ROOT_DIR/start.sh"; fi ;;
esac
