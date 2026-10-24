"""Where downloaded model weights live, and which required models are still missing.

New installs keep the VoxCPM weights inside the project (backend/models) so removing the folder removes
everything. A cache location set by the user (CLONE_VOICE_VOXCPM_CACHE_DIR) or weights already present in
the global Hugging Face / Whisper cache are used as they are and never downloaded a second time.
Run `python -m app.model_cache missing [core]` to list what start.sh still has to download.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path

from app.config import Settings, get_settings


def _global_hub() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _cache_has(cache_dir: Path, model_id: str) -> bool:
    snapshots = cache_dir / f"models--{model_id.replace('/', '--')}" / "snapshots"
    return snapshots.is_dir() and any(snapshots.iterdir())


def resolve_voxcpm_cache_dir(settings: Settings) -> Path | None:
    """The cache_dir handed to VoxCPM; None means the global Hugging Face cache."""
    if settings.voxcpm_cache_dir is not None:
        return settings.voxcpm_cache_dir
    if _cache_has(_global_hub(), settings.voxcpm_model_id):
        return None
    return settings.models_dir / "huggingface"


def whisper_download_root(settings: Settings) -> str | None:
    legacy = Path.home() / ".cache" / "whisper" / f"{settings.whisper_model}.pt"
    project = settings.models_dir / "whisper"
    if legacy.is_file() and not (project / legacy.name).is_file():
        return None
    return str(project)


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def missing_optional_models(settings: Settings) -> list[str]:
    """Song-cover and sound-effect models: large, Apple Silicon only, judged by each adapter's own checks."""
    if not apple_silicon():
        return []
    from app.services.model_router import SoulXSingerAdapter, StableAudioSfxAdapter

    enabled = settings.model_copy(update={"soulx_singer_enabled": True, "stable_audio_sfx_enabled": True})
    missing: list[str] = []
    for adapter in (SoulXSingerAdapter(enabled), StableAudioSfxAdapter(enabled)):
        if adapter.status().status != "available":
            missing.append(adapter.model_id)
    return missing


def missing_models(settings: Settings, *, core_only: bool = False) -> list[str]:
    missing: list[str] = []
    cache = resolve_voxcpm_cache_dir(settings) or _global_hub()
    if importlib.util.find_spec("voxcpm") is None or not _cache_has(cache, settings.voxcpm_model_id):
        missing.append("voxcpm")
    root = whisper_download_root(settings) or str(Path.home() / ".cache" / "whisper")
    if importlib.util.find_spec("whisper") is None or not (Path(root) / f"{settings.whisper_model}.pt").is_file():
        missing.append("whisper")
    return missing if core_only else missing + missing_optional_models(settings)


if __name__ == "__main__":
    if sys.argv[1:2] == ["missing"] and sys.argv[2:] in ([], ["core"]):
        print(" ".join(missing_models(get_settings(), core_only=sys.argv[2:] == ["core"])))
    else:
        raise SystemExit("usage: python -m app.model_cache missing [core]")
