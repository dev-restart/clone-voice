from __future__ import annotations

import subprocess
import sys
import shutil
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


def patch_seed_vc_mps_f0(repo_dir: Path) -> None:
    inference_path = repo_dir / "inference.py"
    source = inference_path.read_text()
    old = """        F0_ori = torch.from_numpy(F0_ori).to(device)[None]
        F0_alt = torch.from_numpy(F0_alt).to(device)[None]
"""
    new = """        if device.type == "mps":
            F0_ori = torch.from_numpy(F0_ori).float().to(device)[None]
            F0_alt = torch.from_numpy(F0_alt).float().to(device)[None]
        else:
            F0_ori = torch.from_numpy(F0_ori).to(device)[None]
            F0_alt = torch.from_numpy(F0_alt).to(device)[None]
"""
    if new in source:
        return
    if old not in source:
        raise SystemExit("Seed-VC inference.py F0 block changed; MPS patch was not applied.")
    inference_path.write_text(source.replace(old, new))


def main() -> None:
    settings = get_settings()
    repo_dir = settings.seed_vc_repo_dir.resolve()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        run(["git", "clone", "https://github.com/Plachtaa/seed-vc", str(repo_dir)])
    elif not (repo_dir / "inference.py").exists():
        raise SystemExit(f"Seed-VC repo exists but inference.py was not found: {repo_dir}")

    venv_dir = repo_dir / ".venv"
    python = venv_dir / "bin" / "python"
    if venv_dir.exists() and not python_is_usable(python):
        shutil.rmtree(venv_dir)
    if not python_is_usable(python):
        run(["uv", "venv", str(venv_dir), "--python", "3.10", "--seed"])

    requirements = repo_dir / "requirements-mac.txt"
    if not requirements.exists():
        requirements = repo_dir / "requirements.txt"
    run([str(python), "-m", "pip", "install", "-r", str(requirements)])
    run([str(python), "-m", "pip", "install", "torchcodec"])
    patch_seed_vc_mps_f0(repo_dir)

    print("Seed-VC setup complete.")
    print(f"Set CLONE_VOICE_SEED_VC_PYTHON={python}")


if __name__ == "__main__":
    main()
