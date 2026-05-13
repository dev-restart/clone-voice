from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def python_is_usable(python: Path) -> bool:
    if not python.exists():
        return False
    result = subprocess.run([str(python), "-c", "import sys; print(sys.version)"], capture_output=True, text=True)
    return result.returncode == 0


def download_model(python: Path, repo_dir: Path, model_id: str, model_dir: Path) -> None:
    script = f"""
from modelscope import snapshot_download
snapshot_download({model_id!r}, local_dir={str(model_dir)!r})
print('CosyVoice model downloaded to {model_dir}')
"""
    run([str(python), "-c", script], cwd=repo_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the dedicated CosyVoice runtime.")
    parser.add_argument(
        "--download-model",
        action="store_true",
        help="Also download the default CosyVoice2 model into the configured model directory.",
    )
    parser.add_argument(
        "--model-id",
        default="iic/CosyVoice2-0.5B",
        help="ModelScope model id to download when --download-model is set.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    repo_dir = settings.cosyvoice_repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        run(["git", "clone", "--recursive", "https://github.com/FunAudioLLM/CosyVoice.git", str(repo_dir)])
    elif not (repo_dir / "cosyvoice" / "cli" / "cosyvoice.py").exists():
        raise SystemExit(f"CosyVoice repo exists but cosyvoice.py was not found: {repo_dir}")
    else:
        run(["git", "submodule", "update", "--init", "--recursive"], cwd=repo_dir)

    venv_dir = repo_dir / ".venv"
    python = venv_dir / "bin" / "python"
    if venv_dir.exists() and not python_is_usable(python):
        shutil.rmtree(venv_dir)
    if not python_is_usable(python):
        run(["uv", "venv", str(venv_dir), "--python", "3.10", "--seed"])

    # CosyVoice pins openai-whisper==20231117, whose build script still imports
    # pkg_resources. Newer setuptools releases can fail that build in isolated
    # environments, so keep a compatible setuptools in the dedicated venv.
    run([str(python), "-m", "pip", "install", "setuptools<81", "wheel"], cwd=repo_dir)
    # pyworld's build metadata imports numpy before pip has installed the full
    # requirements set. Install the build-time basics first in the CosyVoice venv.
    run([str(python), "-m", "pip", "install", "numpy==1.26.4", "cython"], cwd=repo_dir)
    run([str(python), "-m", "pip", "install", "--no-build-isolation", "-r", str(repo_dir / "requirements.txt")], cwd=repo_dir)
    if args.download_model:
        configured_model_dir = Path(settings.cosyvoice_model_dir).expanduser()
        model_dir = configured_model_dir if configured_model_dir.is_absolute() else repo_dir / configured_model_dir
        download_model(python, repo_dir, args.model_id, model_dir)
    print("CosyVoice setup complete.")
    print(f"Set CLONE_VOICE_COSYVOICE_ENABLED=true")
    print(f"Set CLONE_VOICE_COSYVOICE_REPO_DIR={repo_dir}")
    print(f"Set CLONE_VOICE_COSYVOICE_PYTHON={python}")
    if args.download_model:
        print(f"CosyVoice model is available at {repo_dir / settings.cosyvoice_model_dir}.")
    else:
        print("Download a model with: uv run python scripts/setup_cosyvoice.py --download-model")


if __name__ == "__main__":
    main()
