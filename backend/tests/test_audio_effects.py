from pathlib import Path

import numpy as np
import soundfile as sf

from app.services.audio_effects import apply_output_effects
from app.services.generation_helpers import combine_generated_segments


def test_apply_output_effects_creates_processed_wav_without_overwriting_source(tmp_path: Path):
    source = tmp_path / "source.wav"
    output_dir = tmp_path / "outputs"
    sample_rate = 24000
    t = np.linspace(0, 0.4, int(sample_rate * 0.4), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, sample_rate)

    processed, duration = apply_output_effects(
        source,
        output_dir,
        pitch_shift=1.0,
        volume_gain_db=3.0,
        normalize_output=True,
    )

    assert processed.exists()
    assert processed != source
    assert processed.parent == output_dir
    assert duration > 0
    processed_waveform, processed_rate = sf.read(processed)
    assert processed_rate == sample_rate
    assert len(processed_waveform) > 0
    assert np.max(np.abs(processed_waveform)) <= 1.0


def test_apply_output_effects_preserves_source_sample_rate_by_default(tmp_path: Path):
    source = tmp_path / "source-48k.wav"
    output_dir = tmp_path / "outputs"
    sample_rate = 48000
    t = np.linspace(0, 0.4, int(sample_rate * 0.4), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, sample_rate)

    processed, duration = apply_output_effects(source, output_dir, normalize_output=True)

    assert processed.exists()
    _, processed_rate = sf.read(processed)
    assert processed_rate == sample_rate
    assert round(duration, 2) == 0.4


def test_apply_output_effects_preserves_stereo_channels(tmp_path: Path):
    source = tmp_path / "source-stereo.wav"
    output_dir = tmp_path / "outputs"
    sample_rate = 44100
    left = np.full(sample_rate, 0.1, dtype=np.float32)
    right = np.full(sample_rate, -0.2, dtype=np.float32)
    sf.write(source, np.column_stack([left, right]), sample_rate)

    processed, duration = apply_output_effects(source, output_dir, volume_gain_db=1.0, normalize_output=True)

    processed_waveform, processed_rate = sf.read(processed, always_2d=True)
    assert processed_rate == sample_rate
    assert processed_waveform.shape == (sample_rate, 2)
    assert not np.allclose(processed_waveform[:, 0], processed_waveform[:, 1])
    assert duration == 1.0


def test_apply_output_effects_changes_playback_speed_without_changing_sample_rate(tmp_path: Path):
    source = tmp_path / "source-speed.wav"
    output_dir = tmp_path / "outputs"
    sample_rate = 24000
    waveform = np.zeros(sample_rate, dtype=np.float32)
    sf.write(source, waveform, sample_rate)

    processed, duration = apply_output_effects(
        source,
        output_dir,
        playback_speed=0.8,
        normalize_output=False,
    )

    _, processed_rate = sf.read(processed)
    assert processed_rate == sample_rate
    assert 1.20 <= duration <= 1.27


def test_combine_generated_segments_uses_highest_input_sample_rate(tmp_path: Path):
    output_dir = tmp_path / "outputs"
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first_rate = 24000
    second_rate = 48000
    sf.write(first, np.zeros(int(first_rate * 0.25), dtype=np.float32), first_rate)
    sf.write(second, np.zeros(int(second_rate * 0.25), dtype=np.float32), second_rate)

    combined, duration = combine_generated_segments([(first, 250), (second, 0)], output_dir)

    assert combined.exists()
    _, combined_rate = sf.read(combined)
    assert combined_rate == second_rate
    assert round(duration, 2) == 0.75


def _speechlike(sample_rate: int, seconds: float, amplitude: float) -> np.ndarray:
    t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    carrier = np.sin(2 * np.pi * 180 * t) + 0.5 * np.sin(2 * np.pi * 540 * t)
    return (amplitude * envelope * carrier).astype(np.float32)


def test_normalize_output_matches_loudness_between_quiet_and_loud_takes(tmp_path: Path):
    output_dir = tmp_path / "outputs"
    sample_rate = 24000
    levels = []
    for index, amplitude in enumerate((0.03, 0.4)):
        source = tmp_path / f"take-{index}.wav"
        sf.write(source, _speechlike(sample_rate, 4.0, amplitude), sample_rate)
        processed, duration = apply_output_effects(source, output_dir, normalize_output=True)
        waveform, rate = sf.read(processed)
        assert rate == sample_rate
        assert abs(duration - 4.0) < 0.05
        assert np.max(np.abs(waveform)) <= 1.0
        levels.append(20 * np.log10(np.sqrt(np.mean(np.square(waveform)))))

    assert abs(levels[0] - levels[1]) < 2.0


def test_playback_speed_keeps_pitch_and_scales_duration(tmp_path: Path):
    source = tmp_path / "tone.wav"
    sample_rate = 24000
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    sf.write(source, (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), sample_rate)

    processed, duration = apply_output_effects(source, tmp_path / "outputs", playback_speed=1.25, normalize_output=False)

    assert 1.55 <= duration <= 1.65
    waveform, rate = sf.read(processed)
    spectrum = np.abs(np.fft.rfft(waveform))
    peak_hz = np.argmax(spectrum) * rate / len(waveform)
    assert 190 <= peak_hz <= 210


def test_match_speech_level_equalizes_quiet_and_loud_lines_without_changing_length(tmp_path: Path):
    from app.services.audio_effects import match_speech_level

    sample_rate = 24000
    levels = []
    for index, amplitude in enumerate((0.06, 0.5)):
        source = tmp_path / f"line-{index}.wav"
        sf.write(source, _speechlike(sample_rate, 2.0, amplitude), sample_rate)
        processed, duration = match_speech_level(source, tmp_path / "matched")
        waveform, _ = sf.read(processed)
        assert duration == 2.0 and len(waveform) == sample_rate * 2
        assert np.max(np.abs(waveform)) <= 1.0
        levels.append(20 * np.log10(np.sqrt(np.mean(np.square(waveform)))))

    assert abs(levels[0] - levels[1]) < 3.0


def test_combine_segments_keeps_total_length_and_softens_joins(tmp_path: Path):
    first, second = tmp_path / "a.wav", tmp_path / "b.wav"
    sf.write(first, np.full(2400, 0.5, dtype=np.float32), 24000)
    sf.write(second, np.full(2400, 0.5, dtype=np.float32), 24000)

    combined, duration = combine_generated_segments([(first, 100), (second, 0)], tmp_path / "out")

    waveform, _ = sf.read(combined)
    assert round(duration, 3) == 0.3
    assert abs(waveform[0]) < 0.05 and abs(waveform[2399]) < 0.05
