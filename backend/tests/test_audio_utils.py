from pathlib import Path

import numpy as np
import soundfile as sf

from app.services.audio_utils import REFERENCE_SAMPLE_RATE, isolate_speech_audio, normalize_reference_audio


def test_normalize_reference_audio_trims_long_reference_to_15_seconds(tmp_path: Path):
    source = tmp_path / 'long.wav'
    destination = tmp_path / 'normalized.wav'
    sample_rate = REFERENCE_SAMPLE_RATE
    duration_seconds = 20
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    waveform = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, sample_rate)

    normalize_reference_audio(source, destination)

    normalized, normalized_rate = sf.read(destination)
    assert normalized_rate == sample_rate
    assert len(normalized) == sample_rate * 15
    assert np.max(np.abs(normalized)) > 0.01


def test_isolate_speech_audio_writes_speech_focused_wav(tmp_path: Path):
    source = tmp_path / "mixed.wav"
    destination = tmp_path / "voice-only.wav"
    sample_rate = REFERENCE_SAMPLE_RATE
    t = np.linspace(0, 2, int(sample_rate * 2), endpoint=False)
    speech_like = 0.12 * np.sin(2 * np.pi * 440 * t)
    low_rumble = 0.18 * np.sin(2 * np.pi * 45 * t)
    high_noise = 0.04 * np.sin(2 * np.pi * 11000 * t)
    waveform = (speech_like + low_rumble + high_noise).astype(np.float32)
    sf.write(source, waveform, sample_rate)

    isolate_speech_audio(source, destination)

    cleaned, cleaned_rate = sf.read(destination)
    assert cleaned_rate == sample_rate
    assert len(cleaned) == len(waveform)
    assert np.max(np.abs(cleaned)) > 0.01
