#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

OMNIVOICE=0
VOXCPM=0
COSYVOICE=0
SEED_VC=0
INSTALL_DEPS=1
ASSUME_YES=0

usage() {
	cat <<'USAGE'
Usage:
  ./download-models.sh --all
  ./download-models.sh --tts
  ./download-models.sh --omnivoice --voxcpm
  ./download-models.sh --cosyvoice --seed-vc

Options:
  --all          Install backend deps and prepare every supported model.
  --tts          Prepare TTS models: OmniVoice, VoxCPM2, and CosyVoice.
  --omnivoice    Pre-download the OmniVoice Hugging Face model cache.
  --voxcpm       Pre-download the VoxCPM2 Hugging Face model cache.
  --cosyvoice    Install CosyVoice runtime and download CosyVoice2-0.5B.
  --seed-vc      Install Seed-VC runtime for voice conversion.
  --no-deps      Skip backend uv dependency sync.
  -y, --yes      Skip the confirmation prompt.
  -h, --help     Show this help.
USAGE
}

while (($#)); do
	case "$1" in
		--all)
			OMNIVOICE=1
			VOXCPM=1
			COSYVOICE=1
			SEED_VC=1
			;;
		--tts)
			OMNIVOICE=1
			VOXCPM=1
			COSYVOICE=1
			;;
		--omnivoice)
			OMNIVOICE=1
			;;
		--voxcpm)
			VOXCPM=1
			;;
		--cosyvoice)
			COSYVOICE=1
			;;
		--seed-vc)
			SEED_VC=1
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

if ((OMNIVOICE == 0 && VOXCPM == 0 && COSYVOICE == 0 && SEED_VC == 0)); then
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
	((INSTALL_DEPS == 1)) && echo "  - Sync backend dependencies with uv" || echo "  - Skip backend dependency sync"
	((OMNIVOICE == 1)) && echo "  - Download OmniVoice cache"
	((VOXCPM == 1)) && echo "  - Download VoxCPM2 cache"
	((COSYVOICE == 1)) && echo "  - Install CosyVoice runtime and download CosyVoice2-0.5B"
	((SEED_VC == 1)) && echo "  - Install Seed-VC runtime"
}

run_backend() {
	(cd "$BACKEND_DIR" && "$@")
}

ensure_env_file() {
	run_backend cp -n .env.example .env
}

install_backend_deps() {
	if ((INSTALL_DEPS == 0)); then
		return
	fi

	local sync_command=(uv sync)
	if ((OMNIVOICE == 1 || VOXCPM == 1)); then
		((OMNIVOICE == 1)) && sync_command+=(--extra omnivoice)
		((VOXCPM == 1)) && sync_command+=(--extra voxcpm)
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

model_id = sys.argv[1]
path = snapshot_download(repo_id=model_id)
print(f"Downloaded {model_id} to {path}")
PY
}

download_omnivoice() {
	download_hf_model "OmniVoice" "$(settings_value omnivoice_model_id)"
}

download_voxcpm() {
	download_hf_model "VoxCPM2" "$(settings_value voxcpm_model_id)"
}

setup_cosyvoice() {
	run_backend uv run python scripts/setup_cosyvoice.py --download-model
}

setup_seed_vc() {
	run_backend uv run python scripts/setup_seed_vc.py
}

print_env_hint() {
	cat <<'ENV'

Recommended backend/.env values after setup:
CLONE_VOICE_OMNIVOICE_ENABLED=true
CLONE_VOICE_VOXCPM_ENABLED=true
CLONE_VOICE_COSYVOICE_ENABLED=true
CLONE_VOICE_SEED_VC_ENABLED=true
CLONE_VOICE_COSYVOICE_REPO_DIR=vendor/CosyVoice
CLONE_VOICE_COSYVOICE_PYTHON=vendor/CosyVoice/.venv/bin/python
CLONE_VOICE_COSYVOICE_MODEL_DIR=pretrained_models/CosyVoice2-0.5B
CLONE_VOICE_SEED_VC_REPO_DIR=vendor/seed-vc
CLONE_VOICE_SEED_VC_PYTHON=vendor/seed-vc/.venv/bin/python
ENV
}

confirm
ensure_env_file
install_backend_deps

((OMNIVOICE == 1)) && download_omnivoice
((VOXCPM == 1)) && download_voxcpm
((COSYVOICE == 1)) && setup_cosyvoice
((SEED_VC == 1)) && setup_seed_vc

print_env_hint
echo "Model preparation complete."
