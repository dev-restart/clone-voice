#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

VOXCPM=0
WHISPER=0
SOULX_SINGER=0
STABLE_AUDIO_SFX=0
INSTALL_DEPS=1
ASSUME_YES=0

usage() {
	cat <<'USAGE'
Usage:
  ./download-models.sh --all
  ./download-models.sh --tts
  ./download-models.sh --voxcpm --soulx-singer
  ./download-models.sh --sfx
  ./download-models.sh --stt

Options:
  --all          Install backend deps and prepare every supported model.
  --tts          Prepare the VoxCPM2 TTS model.
  --voxcpm       Pre-download the VoxCPM2 Hugging Face model cache.
  --stt          Pre-download the Whisper speech-to-text model.
  --soulx-singer Install SoulX-Singer AI cover runtime and the required SVC weights.
  --sfx          Install Stable Audio 3 Small SFX with the Apple Silicon MLX runtime.
  --no-deps      Skip backend uv dependency sync.
  -y, --yes      Skip the confirmation prompt.
  -h, --help     Show this help.
USAGE
}

while (($#)); do
	case "$1" in
		--all)
			VOXCPM=1
			WHISPER=1
			SOULX_SINGER=1
			STABLE_AUDIO_SFX=1
			;;
		--tts)
			VOXCPM=1
			;;
		--voxcpm)
			VOXCPM=1
			;;
		--stt)
			WHISPER=1
			;;
		--soulx-singer)
			SOULX_SINGER=1
			;;
		--sfx)
			STABLE_AUDIO_SFX=1
			;;
		--no-deps)
			INSTALL_DEPS=0
			;;
		-y|--yes)
			ASSUME_YES=1
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown option: $1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift
done

if ((VOXCPM == 0 && WHISPER == 0 && SOULX_SINGER == 0 && STABLE_AUDIO_SFX == 0)); then
	usage
	exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
	echo "uv is required. Install uv first, then rerun this script." >&2
	exit 1
fi

confirm() {
	print_plan
	if ((ASSUME_YES == 1)); then
		return
	fi
	cat <<'NOTE'
This can download large model files and clone vendor repositories into backend/vendor.
Continue? [y/N]
NOTE
	read -r answer
	case "$answer" in
		y|Y|yes|YES) ;;
		*) echo "Cancelled."; exit 0 ;;
	esac
}

print_plan() {
	echo "Model preparation plan:"
	if ((INSTALL_DEPS == 1)); then echo "  - Sync backend dependencies with uv"; else echo "  - Skip backend dependency sync"; fi
	if ((VOXCPM == 1)); then echo "  - Download VoxCPM2 cache"; fi
	if ((WHISPER == 1)); then echo "  - Download Whisper speech-to-text model"; fi
	if ((SOULX_SINGER == 1)); then echo "  - Install SoulX-Singer Apple Silicon runtime and SVC weights"; fi
	if ((STABLE_AUDIO_SFX == 1)); then echo "  - Install Stable Audio 3 Small SFX MLX runtime and weights"; fi
}

run_backend() {
	(cd "$BACKEND_DIR" && "$@")
}

ensure_env_file() {
	if [[ ! -f "$BACKEND_DIR/.env" ]]; then
		run_backend cp .env.example .env
	fi
}

install_backend_deps() {
	if ((INSTALL_DEPS == 0)); then
		return
	fi

	local sync_command=(uv sync --locked --inexact)
	if ((VOXCPM == 1)); then
		sync_command+=(--extra voxcpm)
	fi
	run_backend "${sync_command[@]}"

	if ((VOXCPM == 1)) && [[ "$(uname -s)" == "Darwin" ]]; then
		run_backend ./scripts/patch_torchcodec_macos.sh
	fi
}

settings_value() {
	local field_name="$1"
	run_backend uv run python - "$field_name" <<'PY'
import sys
from app.config import get_settings

print(getattr(get_settings(), sys.argv[1]))
PY
}

download_hf_model() {
	local label="$1"
	local model_id="$2"
	echo "Downloading $label model cache: $model_id"
	run_backend uv run --with huggingface_hub python - "$model_id" <<'PY'
import sys

from huggingface_hub import snapshot_download

from app.config import get_settings

# VoxCPM reads its weights from settings.voxcpm_cache_dir, so download to exactly that place.
cache_dir = get_settings().voxcpm_cache_dir
model_id = sys.argv[1]
path = snapshot_download(repo_id=model_id, cache_dir=str(cache_dir) if cache_dir else None)
print(f"Downloaded {model_id} to {path}")
PY
}

download_voxcpm() {
	download_hf_model "VoxCPM2" "$(settings_value voxcpm_model_id)"
}

setup_soulx_singer() {
	run_backend uv run python scripts/setup_soulx_singer.py
}

setup_stable_audio_sfx() {
	local repo_dir="$BACKEND_DIR/vendor/stable-audio-3"
	if [[ ! -d "$repo_dir/.git" ]]; then
		git clone --depth 1 https://github.com/Stability-AI/stable-audio-3.git "$repo_dir"
	fi
	# Keep the weights inside the project (backend/models) unless the user chose a Hugging Face location.
	(
		cd "$repo_dir/optimized/mlx"
		HF_HOME="${HF_HOME:-$BACKEND_DIR/models/huggingface}" ./install.sh -y --download sm-sfx
	)
}

set_env_value() {
	local key="$1" value="$2" file="$BACKEND_DIR/.env" tmp
	tmp="$(mktemp)"
	if grep -q "^${key}=" "$file"; then
		awk -v key="$key" -v value="$value" 'BEGIN { prefix = key "=" } index($0, prefix) == 1 { print prefix value; next } { print }' "$file" >"$tmp"
	else
		cat "$file" >"$tmp"
		printf '%s=%s\n' "$key" "$value" >>"$tmp"
	fi
	mv "$tmp" "$file"
}

download_whisper() {
	echo "Downloading Whisper speech-to-text model"
	run_backend uv run python - <<'PY'
import whisper

from app.config import get_settings
from app.model_cache import whisper_download_root

settings = get_settings()
whisper.load_model(settings.whisper_model, download_root=whisper_download_root(settings))
print(f"Whisper model ready: {settings.whisper_model}")
PY
}

enable_installed_models() {
	# Turn on exactly what was installed so the app works without hand-editing .env.
	if ((VOXCPM == 1)); then set_env_value CLONE_VOICE_VOXCPM_ENABLED true; fi
	if ((SOULX_SINGER == 1)); then
		set_env_value CLONE_VOICE_SOULX_SINGER_ENABLED true
		set_env_value CLONE_VOICE_SOULX_SINGER_REPO_DIR vendor/SoulX-Singer-MLX
		set_env_value CLONE_VOICE_SOULX_SINGER_PYTHON vendor/SoulX-Singer-MLX/.venv/bin/python
	fi
	if ((STABLE_AUDIO_SFX == 1)); then
		set_env_value CLONE_VOICE_STABLE_AUDIO_SFX_ENABLED true
		set_env_value CLONE_VOICE_STABLE_AUDIO_REPO_DIR vendor/stable-audio-3
		set_env_value CLONE_VOICE_STABLE_AUDIO_PYTHON vendor/stable-audio-3/optimized/mlx/.venv/bin/python
	fi
	echo "Updated backend/.env for the installed models."
}

confirm
ensure_env_file
install_backend_deps

if ((VOXCPM == 1)); then download_voxcpm; fi
if ((WHISPER == 1)); then download_whisper; fi
if ((SOULX_SINGER == 1)); then setup_soulx_singer; fi
if ((STABLE_AUDIO_SFX == 1)); then setup_stable_audio_sfx; fi

enable_installed_models
echo "Model preparation complete."
