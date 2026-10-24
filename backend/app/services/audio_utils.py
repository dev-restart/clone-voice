from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


REFERENCE_SAMPLE_RATE = 24000
STT_SAMPLE_RATE = 16000
MAX_REFERENCE_SECONDS = 15
VOICE_ISOLATION_SAMPLE_RATE = 24000
VOICE_ISOLATION_FULL_SEPARATION_MAX_SECONDS = 180


@dataclass(frozen=True)
class PreparedReferenceAudio:
    waveform: np.ndarray
    was_condensed: bool


def prepare_reference_audio(
    source: Path,
    sample_rate: int = REFERENCE_SAMPLE_RATE,
    trim_start: float | None = None,
    trim_end: float | None = None,
) -> PreparedReferenceAudio:
    try:
        import librosa

        waveform, _ = librosa.load(str(source), sr=sample_rate, mono=True)
        if trim_start is not None or trim_end is not None:
            start_sample = max(0, int((trim_start or 0) * sample_rate))
            end_sample = int(trim_end * sample_rate) if trim_end is not None else waveform.size
            waveform = waveform[start_sample:max(start_sample, min(end_sample, waveform.size))]
        non_silent = librosa.effects.split(waveform, top_db=35)
        if len(non_silent) and trim_start is None and trim_end is None:
            waveform = np.concatenate([waveform[start:end] for start, end in non_silent])
    except Exception as exc:
        raise RuntimeError(f"Reference audio could not be decoded. Please upload a clear WAV/MP3/M4A/WebM audio file. ({exc})") from exc

    if waveform.size == 0:
        raise RuntimeError("Reference audio did not contain any samples.")

    waveform = np.asarray(waveform, dtype=np.float32)
    pre_trim_length = waveform.size
    if trim_start is None and trim_end is None:
        waveform = trim_reference_waveform(waveform, sample_rate)
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if peak > 1.0:
        waveform = waveform / peak
    return PreparedReferenceAudio(waveform=waveform, was_condensed=waveform.size < pre_trim_length)


def load_reference_audio(source: Path, sample_rate: int = REFERENCE_SAMPLE_RATE) -> np.ndarray:
    return prepare_reference_audio(source, sample_rate).waveform


def trim_reference_waveform(waveform: np.ndarray, sample_rate: int, max_seconds: int = MAX_REFERENCE_SECONDS) -> np.ndarray:
    max_samples = int(sample_rate * max_seconds)
    if waveform.size <= max_samples:
        return waveform

    energy = np.square(waveform.astype(np.float32, copy=False))
    window_energy = np.convolve(energy, np.ones(max_samples, dtype=np.float32), mode="valid")
    start = int(np.argmax(window_energy)) if window_energy.size else 0
    end = start + max_samples
    return waveform[start:end]


def normalize_reference_audio(
    source: Path,
    destination: Path,
    sample_rate: int = REFERENCE_SAMPLE_RATE,
    trim_start: float | None = None,
    trim_end: float | None = None,
) -> Path:
    """Convert uploaded reference audio to mono WAV for model compatibility."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    waveform = prepare_reference_audio(source, sample_rate, trim_start=trim_start, trim_end=trim_end).waveform
    sf.write(destination, waveform, sample_rate)
    return destination


def normalize_stt_audio(
    source: Path,
    destination: Path,
    sample_rate: int = STT_SAMPLE_RATE,
    trim_start: float | None = None,
    trim_end: float | None = None,
) -> Path:
    """Convert audio to a Whisper-friendly mono WAV."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        import librosa

        waveform, _ = librosa.load(str(source), sr=sample_rate, mono=True)
    except Exception as exc:
        raise RuntimeError(f"STT audio could not be decoded. ({exc})") from exc
    if trim_start is not None or trim_end is not None:
        start_sample = max(0, int((trim_start or 0) * sample_rate))
        end_sample = int(trim_end * sample_rate) if trim_end is not None else waveform.size
        waveform = waveform[start_sample:max(start_sample, min(end_sample, waveform.size))]
    if waveform.size == 0:
        raise RuntimeError("STT audio did not contain any samples.")
    waveform = np.asarray(waveform, dtype=np.float32)
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if peak > 1.0:
        waveform = waveform / peak
    sf.write(destination, waveform, sample_rate)
    return destination


def normalize_voice_conversion_audio(
    source: Path,
    destination: Path,
    sample_rate: int = REFERENCE_SAMPLE_RATE,
    trim_start: float | None = None,
    trim_end: float | None = None,
) -> Path:
    """Convert source audio to mono WAV for direct voice conversion."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        import librosa

        waveform, _ = librosa.load(str(source), sr=sample_rate, mono=True)
    except Exception as exc:
        raise RuntimeError(f"Voice conversion audio could not be decoded. ({exc})") from exc
    if trim_start is not None or trim_end is not None:
        start_sample = max(0, int((trim_start or 0) * sample_rate))
        end_sample = int(trim_end * sample_rate) if trim_end is not None else waveform.size
        waveform = waveform[start_sample:max(start_sample, min(end_sample, waveform.size))]
    if waveform.size == 0:
        raise RuntimeError("Voice conversion audio did not contain any samples.")
    waveform = np.asarray(waveform, dtype=np.float32)
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if peak > 1.0:
        waveform = waveform / peak
    sf.write(destination, waveform, sample_rate)
    return destination


def normalize_music_cover_audio(
    source: Path,
    destination: Path,
    trim_start: float | None = None,
    trim_end: float | None = None,
) -> Path:
    """Decode a music source without discarding its stereo accompaniment."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        import librosa

        waveform, sample_rate = librosa.load(str(source), sr=None, mono=False)
    except Exception as exc:
        raise RuntimeError(f"AI cover audio could not be decoded. ({exc})") from exc
    waveform = np.asarray(waveform, dtype=np.float32)
    if waveform.ndim == 1:
        waveform = waveform[np.newaxis, :]
    if trim_start is not None or trim_end is not None:
        start_sample = max(0, int((trim_start or 0) * sample_rate))
        end_sample = int(trim_end * sample_rate) if trim_end is not None else waveform.shape[-1]
        waveform = waveform[:, start_sample:max(start_sample, min(end_sample, waveform.shape[-1]))]
    if waveform.size == 0 or waveform.shape[-1] == 0:
        raise RuntimeError("AI cover audio did not contain any samples.")
    peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    if peak > 1.0:
        waveform = waveform / peak
    sf.write(destination, waveform.T, sample_rate)
    return destination


def isolate_speech_audio(
    source: Path,
    destination: Path,
    sample_rate: int = VOICE_ISOLATION_SAMPLE_RATE,
) -> Path:
    """Reduce background music/effects and write a speech-focused mono WAV.

    This is a lightweight local cleanup path for imported media samples. It
    does not guarantee perfect vocal isolation like a dedicated source-separation
    model, but it improves voice-cloning references by keeping the speech band,
    suppressing repetitive background material, and normalizing the result.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        import librosa
        from scipy.signal import butter, sosfiltfilt

        waveform, _ = librosa.load(str(source), sr=sample_rate, mono=True)
    except Exception as exc:
        raise RuntimeError(f"Speech-only cleanup could not decode the audio. ({exc})") from exc

    if waveform.size == 0:
        raise RuntimeError("Speech-only cleanup did not find any audio samples.")

    waveform = np.asarray(waveform, dtype=np.float32)
    duration_seconds = waveform.size / sample_rate
    try:
        sos = butter(6, [90, 7600], btype="bandpass", fs=sample_rate, output="sos")
        waveform = sosfiltfilt(sos, waveform).astype(np.float32)
    except Exception:
        waveform = np.asarray(waveform, dtype=np.float32)

    if duration_seconds <= VOICE_ISOLATION_FULL_SEPARATION_MAX_SECONDS:
        waveform = _separate_foreground_speech(waveform, sample_rate)
    waveform = _spectral_gate(waveform, sample_rate)
    waveform = _normalize_waveform(waveform)
    sf.write(destination, waveform, sample_rate)
    return destination


def _separate_foreground_speech(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    try:
        import librosa

        stft = librosa.stft(waveform, n_fft=2048, hop_length=512)
        magnitude, phase = librosa.magphase(stft)
        if magnitude.size == 0 or magnitude.shape[1] < 4:
            return waveform
        width = max(1, min(magnitude.shape[1], librosa.time_to_frames(2.0, sr=sample_rate, hop_length=512)))
        background = librosa.decompose.nn_filter(magnitude, aggregate=np.median, metric="cosine", width=width)
        background = np.minimum(magnitude, background)
        foreground_mask = librosa.util.softmask(magnitude - background, 8 * background, power=2)
        foreground = foreground_mask * magnitude
        separated = librosa.istft(foreground * phase, hop_length=512, length=waveform.size)
        return np.asarray(separated, dtype=np.float32)
    except Exception:
        return waveform


def _spectral_gate(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    try:
        import librosa

        stft = librosa.stft(waveform, n_fft=1024, hop_length=256)
        magnitude, phase = librosa.magphase(stft)
        noise_floor = np.percentile(magnitude, 18, axis=1, keepdims=True)
        speech_energy = np.maximum(magnitude - noise_floor, 0)
        mask = librosa.util.softmask(speech_energy, 1.5 * noise_floor, power=2)
        cleaned = librosa.istft(magnitude * mask * phase, hop_length=256, length=waveform.size)
        return np.asarray(cleaned, dtype=np.float32)
    except Exception:
        return waveform


def _normalize_waveform(waveform: np.ndarray) -> np.ndarray:
    waveform = np.nan_to_num(np.asarray(waveform, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    if waveform.size == 0:
        return waveform
    waveform = waveform - float(np.mean(waveform))
    peak = float(np.max(np.abs(waveform)))
    if peak > 0:
        waveform = waveform / peak * 0.92
    return waveform.astype(np.float32)
