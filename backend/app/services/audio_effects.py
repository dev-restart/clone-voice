import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

# 말하는 음성의 표준 목표 음량입니다. 팟캐스트·내레이션 납품 기준(-16 LUFS)을 따릅니다.
TARGET_LOUDNESS_LUFS = -16.0
TARGET_TRUE_PEAK_DB = -1.5
_FFMPEG_TIMEOUT_SECONDS = 120


def _ffmpeg_binary() -> str | None:
    return shutil.which("ffmpeg")


def _run_ffmpeg_on_waveform(waveform: np.ndarray, sample_rate: int, audio_filter: str) -> tuple[np.ndarray, str]:
    """(channels, samples) waveform에 ffmpeg 필터를 적용합니다. 필터 stderr도 함께 돌려줍니다."""
    binary = _ffmpeg_binary()
    if binary is None:
        raise RuntimeError("ffmpeg is not installed.")
    with tempfile.TemporaryDirectory(prefix="clone-voice-fx-") as workdir:
        source = Path(workdir) / "in.wav"
        destination = Path(workdir) / "out.wav"
        sf.write(source, waveform.T, sample_rate, subtype="FLOAT")
        result = subprocess.run(
            [binary, "-hide_banner", "-nostats", "-y", "-i", str(source), "-af", audio_filter, "-c:a", "pcm_f32le", str(destination)],
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0 or not destination.exists():
            raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffmpeg failed")
        processed, _ = sf.read(destination, dtype="float32", always_2d=True)
    return processed.T, result.stderr


def _stretch_speech(waveform: np.ndarray, sample_rate: int, rate: float) -> np.ndarray:
    """음높이를 유지하며 속도만 바꿉니다. 음성에는 WSOLA 계열 atempo가 phase vocoder보다 덜 울립니다."""
    rate = max(0.5, min(2.0, rate))
    if _ffmpeg_binary() is not None:
        try:
            stretched, _ = _run_ffmpeg_on_waveform(waveform, sample_rate, f"atempo={rate:.4f}")
            return stretched
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
    import librosa

    return librosa.effects.time_stretch(waveform, rate=rate)


def _loudness_normalize(waveform: np.ndarray, sample_rate: int) -> np.ndarray | None:
    """EBU R128 두 번 측정 방식으로 음량을 맞춥니다. 측정할 수 없으면 None을 돌려줍니다."""
    if _ffmpeg_binary() is None or waveform.size == 0 or waveform.shape[-1] < sample_rate * 0.5:
        return None
    target = f"I={TARGET_LOUDNESS_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA=11"
    try:
        _, report = _run_ffmpeg_on_waveform(waveform, sample_rate, f"loudnorm={target}:print_format=json")
        match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", report, re.DOTALL)
        if match is None:
            return None
        measured = json.loads(match.group(0))
        input_i = float(measured["input_i"])
        if not np.isfinite(input_i) or input_i < -60:
            return None
        second_pass = (
            f"loudnorm={target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true,aresample={sample_rate}"
        )
        normalized, _ = _run_ffmpeg_on_waveform(waveform, sample_rate, second_pass)
        # loudnorm은 48kHz로 resample할 수 있어 길이가 달라지면 원래 속도를 보존하도록 폐기합니다.
        if normalized.shape[0] != waveform.shape[0] or abs(normalized.shape[-1] - waveform.shape[-1]) > sample_rate * 0.05:
            return None
        return normalized
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def apply_output_effects(
    source: Path,
    output_dir: Path,
    *,
    pitch_shift: float = 0.0,
    volume_gain_db: float = 0.0,
    playback_speed: float = 1.0,
    normalize_output: bool = True,
    sample_rate: int | None = None,
) -> tuple[Path, float]:
    output_dir.mkdir(parents=True, exist_ok=True)
    waveform, loaded_rate = sf.read(source, dtype="float32", always_2d=True)
    waveform = waveform.T

    target_rate = int(sample_rate or loaded_rate)

    if loaded_rate != target_rate:
        try:
            import librosa

            waveform = librosa.resample(waveform, orig_sr=loaded_rate, target_sr=target_rate, axis=-1)
        except Exception as exc:
            raise RuntimeError(f"Could not resample generated audio: {exc}") from exc

    if abs(pitch_shift) >= 0.01:
        try:
            import librosa

            waveform = librosa.effects.pitch_shift(y=waveform, sr=target_rate, n_steps=pitch_shift)
        except Exception as exc:
            raise RuntimeError(f"Could not apply pitch shift: {exc}") from exc

    if abs(playback_speed - 1.0) >= 0.01:
        try:
            waveform = _stretch_speech(waveform, target_rate, playback_speed)
        except Exception as exc:
            raise RuntimeError(f"Could not apply playback speed: {exc}") from exc

    if abs(volume_gain_db) >= 0.01:
        waveform = waveform * float(10 ** (volume_gain_db / 20))

    if normalize_output:
        normalized = _loudness_normalize(waveform, target_rate)
        if normalized is not None:
            waveform = normalized
        else:
            peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
            if peak > 0:
                waveform = waveform / peak * 0.94

    waveform = np.clip(waveform, -1.0, 1.0).astype(np.float32)
    destination = output_dir / f"{uuid4().hex}.wav"
    output_waveform = waveform[0] if waveform.shape[0] == 1 else waveform.T
    sf.write(destination, output_waveform, target_rate, subtype="PCM_16")
    return destination, float(waveform.shape[-1] / target_rate)


def match_speech_level(
    source: Path,
    output_dir: Path,
    *,
    target_db: float = -20.0,
    max_gain_db: float = 12.0,
) -> tuple[Path, float]:
    """말하는 구간의 평균 음량을 target_db(RMS)로 맞춥니다. 길이는 바꾸지 않습니다.

    대화 오디오는 목소리마다 녹음 레벨이 달라 한 화자만 크게 들리기 쉽습니다. 합치기 전에 단락별로
    맞추면 전체 음량 맞춤이 화자 간 차이를 키우지 않습니다.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    waveform, rate = sf.read(source, dtype="float32", always_2d=True)
    mono = waveform.mean(axis=1)
    frame = max(1, int(rate * 0.02))
    usable = (len(mono) // frame) * frame
    gain = 1.0
    if usable:
        frames = mono[:usable].reshape(-1, frame)
        frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
        active = frame_rms[frame_rms > 10 ** (-45 / 20)]
        if active.size:
            speech_rms = float(np.sqrt(np.mean(np.square(active))))
            gain_db = max(-max_gain_db, min(max_gain_db, target_db - 20 * np.log10(speech_rms)))
            gain = float(10 ** (gain_db / 20))
            peak = float(np.max(np.abs(waveform)))
            if peak * gain > 0.98:
                gain = 0.98 / peak
    destination = output_dir / f"{uuid4().hex}.wav"
    sf.write(destination, np.clip(waveform * gain, -1.0, 1.0), rate, subtype="PCM_16")
    return destination, float(waveform.shape[0] / rate)
