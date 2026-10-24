from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


REPOSITORY_URL = "https://github.com/ailuntx/SoulX-Singer-MLX.git"
REPOSITORY_COMMIT = "cc5b3054188e8f0d1cab13c07a3e7b6f339bd871"
RUNTIME_PACKAGES = [
    "torch==2.8.0",
    "torchaudio==2.8.0",
    "numpy<2",
    "accelerate==1.11.0",
    "transformers==4.41.2",
    "omegaconf==2.3.0",
    "librosa==0.11.0",
    "scipy==1.15.3",
    "soundfile==0.13.1",
    "tqdm==4.67.1",
    "mlx",
    "safetensors",
    "huggingface_hub",
    "beartype==0.22.9",
    "einops==0.8.2",
    "loralib==0.1.2",
    "ml_collections==1.1.0",
    "matplotlib==3.10.8",
    "rotary_embedding_torch==0.8.9",
    "wandb==0.24.2",
    "pyyaml",
]


def run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def python_is_usable(python: Path) -> bool:
    if not python.exists():
        return False
    result = subprocess.run([str(python), "-c", "import sys; print(sys.version)"], capture_output=True, text=True)
    return result.returncode == 0


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"SoulX-Singer source changed; {label} patch was not applied: {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def patch_mps_runtime(repo_dir: Path) -> None:
    separator_path = repo_dir / "preprocess/tools/vocal_separation/model.py"
    replace_once(
        separator_path,
        "        sep_model = sep_model.half()\n        sep_model = sep_model.to(device)\n",
        "        if str(device).startswith(\"cuda\"):\n            sep_model = sep_model.half()\n        else:\n            sep_model = sep_model.float()\n        sep_model = sep_model.to(device)\n",
        "MPS FP32 separator",
    )
    replace_once(
        separator_path,
        "            dereverb_model = dereverb_model.half()\n            dereverb_model = dereverb_model.to(device)\n",
        "            if str(device).startswith(\"cuda\"):\n                dereverb_model = dereverb_model.half()\n            else:\n                dereverb_model = dereverb_model.float()\n            dereverb_model = dereverb_model.to(device)\n",
        "MPS FP32 dereverb",
    )

    roformer_path = repo_dir / "preprocess/tools/vocal_separation/modules/bs_roformer/mel_band_roformer.py"
    replace_once(
        roformer_path,
        "        masks_summed = torch.zeros_like(stft_repr_expanded_stems).scatter_add_(2, scatter_indices, masks)\n",
        "        if masks.device.type == 'mps':\n            # MPS cannot scatter complex tensors, so accumulate each float plane.\n            masks_summed = torch.complex(\n                torch.zeros_like(stft_repr_expanded_stems.real).scatter_add_(2, scatter_indices, masks.real),\n                torch.zeros_like(stft_repr_expanded_stems.imag).scatter_add_(2, scatter_indices, masks.imag),\n            )\n        else:\n            masks_summed = torch.zeros_like(stft_repr_expanded_stems).scatter_add_(2, scatter_indices, masks)\n",
        "MPS complex scatter",
    )


def download_snapshot(python: Path, repo_id: str, local_dir: Path, patterns: list[str]) -> None:
    code = """
import json
import sys
from huggingface_hub import snapshot_download

repo_id, local_dir, patterns_json = sys.argv[1:]
snapshot_download(repo_id=repo_id, local_dir=local_dir, allow_patterns=json.loads(patterns_json))
"""
    import json

    run([str(python), "-c", code, repo_id, str(local_dir), json.dumps(patterns)])


def download_models(repo_dir: Path, python: Path) -> None:
    download_snapshot(
        python,
        "mlx-community/SoulX-Singer-bf16",
        repo_dir / "models/SoulX-Singer-bf16",
        ["svc/*", "config.json", "config.yaml", "mlx_manifest.json"],
    )
    download_snapshot(
        python,
        "openai/whisper-base",
        repo_dir / "pretrained_models/openai__whisper-base",
        ["*.json", "*.txt", "model.safetensors"],
    )
    download_snapshot(
        python,
        "Soul-AILab/SoulX-Singer-Preprocess",
        repo_dir / "pretrained_models/SoulX-Singer-Preprocess",
        ["rmvpe/rmvpe.pt", "mel-band-roformer-karaoke/*"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the SoulX-Singer Apple Silicon runtime.")
    parser.add_argument("--skip-download", action="store_true", help="Install the runtime without model weights.")
    args = parser.parse_args()

    settings = get_settings()
    repo_dir = settings.soulx_singer_repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        run(["git", "clone", "--filter=blob:none", REPOSITORY_URL, str(repo_dir)])
        run(["git", "checkout", "--detach", REPOSITORY_COMMIT], cwd=repo_dir)
    elif not (repo_dir / "scripts/inference_mlx_bridge.py").exists():
        raise SystemExit(f"SoulX-Singer-MLX repo is incomplete: {repo_dir}")

    venv_dir = repo_dir / ".venv"
    python = venv_dir / "bin/python"
    if venv_dir.exists() and not python_is_usable(python):
        shutil.rmtree(venv_dir)
    if not python_is_usable(python):
        run(["uv", "venv", str(venv_dir), "--python", "3.10", "--seed"])
    run(["uv", "pip", "install", "--python", str(python), *RUNTIME_PACKAGES])
    patch_mps_runtime(repo_dir)
    if not args.skip_download:
        download_models(repo_dir, python)

    print("SoulX-Singer Apple Silicon runtime is ready.")
    print(f"Set CLONE_VOICE_SOULX_SINGER_PYTHON={python}")


if __name__ == "__main__":
    main()
