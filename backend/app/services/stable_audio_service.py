from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import soundfile as sf

from app.config import Settings


STABLE_AUDIO_SAMPLE_RATE = 44_100


@dataclass(frozen=True)
class StableAudioStatus:
    available: bool
    loaded: bool
    message: str | None = None


class StableAudioSfxEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def repo_dir(self) -> Path:
        return self.settings.stable_audio_repo_dir.resolve()

    @property
    def runtime_dir(self) -> Path:
        return self.repo_dir / "optimized" / "mlx"

    @property
    def script_path(self) -> Path:
        return self.runtime_dir / "scripts" / "sa3_mlx.py"

    @property
    def python_executable(self) -> Path:
        if self.settings.stable_audio_python:
            return Path(self.settings.stable_audio_python).expanduser().resolve()
        return self.runtime_dir / ".venv" / "bin" / "python"

    @property
    def weight_paths(self) -> tuple[Path, ...]:
        weight_dir = self.runtime_dir / "models" / "mlx"
        return (
            weight_dir / "t5gemma_f16.npz",
            weight_dir / "dit_sm-sfx_f16.npz",
            weight_dir / "same_s_decoder_f32.npz",
        )

    def status(self) -> StableAudioStatus:
        if not self.settings.stable_audio_sfx_enabled:
            return StableAudioStatus(False, False, "Disabled by CLONE_VOICE_STABLE_AUDIO_SFX_ENABLED=false.")
        if sys.platform != "darwin":
            return StableAudioStatus(False, False, "Stable Audio MLX runtime requires Apple Silicon macOS.")
        if not self.script_path.exists():
            return StableAudioStatus(False, False, f"Stable Audio 3 runtime was not found at {self.runtime_dir}.")
        if not self.python_executable.exists():
            return StableAudioStatus(
                False,
                False,
                f"Stable Audio Python environment was not found at {self.python_executable}. Run ./download-models.sh --sfx.",
            )
        missing_weights = [path.name for path in self.weight_paths if not path.exists()]
        if missing_weights:
            return StableAudioStatus(
                False,
                False,
                f"Stable Audio SFX weights are missing: {', '.join(missing_weights)}. Run ./download-models.sh --sfx.",
            )
        return StableAudioStatus(True, True)

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        duration_seconds: float,
        steps: int,
        guidance_scale: float,
        seed: int,
    ) -> tuple[Path, float]:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.message or "Stable Audio SFX is unavailable.")

        output_path = (self.settings.outputs_dir / f"{uuid4().hex}-sfx.wav").resolve()
        command = [
            str(self.python_executable),
            str(self.script_path),
            "--prompt",
            prompt,
            "--negative-prompt",
            negative_prompt,
            "--dit",
            "sm-sfx",
            "--decoder",
            "same-s",
            "--seconds",
            str(duration_seconds),
            "--steps",
            str(steps),
            "--seed",
            str(seed),
            "--cfg",
            str(guidance_scale),
            "--out",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.runtime_dir,
                capture_output=True,
                text=True,
                timeout=self.settings.stable_audio_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Stable Audio generation timed out after {self.settings.stable_audio_timeout_seconds}s."
            ) from exc

        if completed.returncode != 0 or not output_path.exists():
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            raise RuntimeError(detail[-1600:] or "Stable Audio did not produce a WAV output file.")

        info = sf.info(output_path)
        duration = float(info.frames / info.samplerate) if info.samplerate else duration_seconds
        return output_path, duration
