from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf


def apply_output_effects(
    source: Path,
    output_dir: Path,
    *,
    pitch_shift: float = 0.0,
    volume_gain_db: float = 0.0,
    normalize_output: bool = True,
    sample_rate: int | None = None,
) -> tuple[Path, float]:
    output_dir.mkdir(parents=True, exist_ok=True)
    waveform, loaded_rate = sf.read(source, dtype="float32", always_2d=False)
    if waveform.ndim > 1:
        waveform = np.mean(waveform, axis=1)

    target_rate = int(sample_rate or loaded_rate)

    if loaded_rate != target_rate:
        try:
            import librosa

            waveform = librosa.resample(waveform, orig_sr=loaded_rate, target_sr=target_rate)
        except Exception as exc:
            raise RuntimeError(f"Could not resample generated audio: {exc}") from exc

    if abs(pitch_shift) >= 0.01:
        try:
            import librosa

            waveform = librosa.effects.pitch_shift(y=waveform, sr=target_rate, n_steps=pitch_shift)
        except Exception as exc:
            raise RuntimeError(f"Could not apply pitch shift: {exc}") from exc

    if abs(volume_gain_db) >= 0.01:
        waveform = waveform * float(10 ** (volume_gain_db / 20))

    if normalize_output:
        peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
        if peak > 0:
            waveform = waveform / peak * 0.94

    waveform = np.clip(waveform, -1.0, 1.0).astype(np.float32)
    destination = output_dir / f"{uuid4().hex}.wav"
    sf.write(destination, waveform, target_rate, subtype="PCM_16")
    return destination, float(len(waveform) / target_rate)
