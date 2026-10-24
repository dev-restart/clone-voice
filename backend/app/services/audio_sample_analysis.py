"""Local speech-region suggestions. Scores rank candidates; they are not clone-quality probabilities."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from app.config import Settings
from app.i18n import current_locale, tr

HOP_SECONDS = 0.1
SAMPLE_RATE = 16000
MAX_DURATION = 3600
MAX_SOURCE_BYTES = 512 * 1024 * 1024
_BUILD_LOCK = threading.Lock()
_ANALYSIS_SLOT = threading.BoundedSemaphore(1)
_VERSION = "sample-analysis-v2"
SPEECH_MIN = .55
MUSIC_HIGH = .65
SINGING_HIGH = .30


class SampleAnalysisRequest(BaseModel):
    audio_url: str = Field(min_length=1, max_length=512)


class SampleTranscriptRequest(SampleAnalysisRequest):
    provider: str = Field(default="whisper", pattern=r"^(whisper|apple-speech)$")
    language: str | None = Field(default=None, max_length=32)
    start: float = Field(default=0, ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


def resolve_uploaded_audio(audio_url: str, settings: Settings) -> Path:
    match = re.fullmatch(r"/api/files/uploads/([A-Za-z0-9][A-Za-z0-9._-]{0,200})", audio_url)
    if not match:
        raise ValueError(tr("이 앱에 가져온 오디오 파일만 분석할 수 있습니다.", "Only audio imported into this app can be analyzed."))
    root = settings.uploads_dir.resolve()
    path = root / match.group(1)
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        raise ValueError(tr("분석할 오디오 파일을 찾을 수 없습니다. 파일을 다시 가져와 주세요.", "The audio file to analyze was not found. Import it again."))
    if not 0 < path.stat().st_size <= MAX_SOURCE_BYTES:
        raise ValueError(tr("분석할 오디오는 비어 있지 않은 512MB 이하 파일이어야 합니다.", "The audio to analyze must be a non-empty file of 512 MB or less."))
    return path


def decode_analysis_audio(source: Path, destination: Path, *, start: float = 0, end: float | None = None) -> float:
    """Bound decode duration and use one mono file for signal and native time coordinates."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        duration = float(json.loads(probe.stdout)["format"]["duration"])
        if probe.returncode or not math.isfinite(duration) or duration <= 0:
            raise ValueError
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise ValueError(tr("오디오 길이를 확인하지 못했습니다. WAV·MP3·M4A 파일을 확인해 주세요.", "Could not determine the audio length. Check that it is a WAV, MP3 or M4A file.")) from exc
    if duration > MAX_DURATION:
        raise ValueError(tr("구간 분석은 60분 이하의 오디오를 지원합니다.", "Range analysis supports audio up to 60 minutes."))
    stop = duration if end is None else min(end, duration)
    if not math.isfinite(start) or start < 0 or start >= stop:
        raise ValueError(tr("오디오 안에서 올바른 시작·끝 구간을 선택해 주세요.", "Choose a valid start and end within the audio."))
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", str(start), "-i", str(source),
             "-t", str(stop - start), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-c:a", "pcm_s16le", str(destination)],
            capture_output=True, text=True, check=False, timeout=90,
        )
        if result.returncode or not destination.is_file():
            raise ValueError(tr("오디오를 분석용으로 변환하지 못했습니다.", "Could not convert the audio for analysis."))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(tr("오디오 변환을 완료하지 못했습니다. ffmpeg 설치와 파일을 확인해 주세요.", "Could not finish converting the audio. Check the ffmpeg installation and the file.")) from exc
    return stop - start


def signal_features(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> dict:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError(tr("분석할 수 있는 오디오 신호가 없습니다.", "There is no audio signal to analyze."))
    hop = max(1, round(sample_rate * HOP_SECONDS))
    count = math.ceil(audio.size / hop)
    padded = np.pad(audio, (0, count * hop - audio.size)).reshape(count, hop)
    rms = np.sqrt(np.mean(np.square(padded), axis=1))
    clipped = np.mean(np.abs(padded) >= 0.995, axis=1)
    db = 20 * np.log10(np.maximum(rms, 1e-8))
    # A relative threshold finds quieter speech, with an absolute floor for silence.
    threshold = max(-52.0, min(-30.0, float(np.percentile(db, 85)) - 25.0))
    return {"active": db > threshold, "clipped": clipped, "db": db, "duration": audio.size / sample_rate}


def _native_scores(frames: list[dict], count: int, duration: float) -> tuple[np.ndarray, np.ndarray]:
    totals = np.zeros((count, 3), dtype=np.float32)
    coverage = np.zeros(count, dtype=np.float32)
    if not frames or len(frames) > 8000:
        raise RuntimeError(tr("Apple 소리 분석이 유효한 구간을 반환하지 않았습니다.", "Apple sound analysis returned no valid segments."))
    for item in frames:
        values = [float(item[key]) for key in ("start", "end", "speech", "music", "singing")]
        start, end, *scores = values
        if (not all(math.isfinite(value) for value in values) or not 0 <= start < end <= duration + 0.1
                or not all(0 <= value <= 1 for value in scores)):
            raise RuntimeError(tr("Apple 소리 분석의 시간 정보를 확인하지 못했습니다.", "Could not read the timing from Apple sound analysis."))
        lo = max(0, int(start / HOP_SECONDS))
        hi = min(count, math.ceil(end / HOP_SECONDS))
        totals[lo:hi] += scores
        coverage[lo:hi] += 1
    return totals / np.maximum(coverage[:, None], 1), coverage > 0


def _runs(values: np.ndarray) -> list[tuple[int, int, str]]:
    if not len(values):
        return []
    points = [0, *(np.flatnonzero(values[1:] != values[:-1]) + 1).tolist(), len(values)]
    return [(lo, hi, str(values[lo])) for lo, hi in zip(points, points[1:])]


def recommend_regions(features: dict, frames: list[dict] | None = None) -> dict:
    active = features["active"]
    count, duration = len(active), float(features["duration"])
    native = frames is not None
    scores, covered = _native_scores(frames, count, duration) if native else (np.zeros((count, 3)), np.zeros(count, dtype=bool))
    speech, music, singing = scores.T
    # The three classifier confidences are independent; thresholds apply separately.
    kinds = np.where(active, "sound", "silence").astype("<U8")
    if native:
        kinds[(speech >= .55) & covered & active] = "speech"
        kinds[(music >= .35) & covered & active] = "music"
        kinds[(speech >= .55) & (music >= .35) & covered & active] = "mixed"
        kinds[(singing >= .35) & covered & active] = "singing"
    # A 0.5-second display grid keeps long recordings readable without thousands of DOM elements.
    display = []
    for lo in range(0, count, 5):
        window = kinds[lo:lo + 5].tolist()
        display.append(max(dict.fromkeys(window), key=window.count))
    regions = [{"start": round(lo * .5, 2), "end": round(min(hi * .5, duration), 2), "kind": kind}
               for lo, hi, kind in _runs(np.asarray(display))]

    # Mild music confidence can coexist with clear speech. Reject strong music and
    # singing, and use average music confidence to rank the remaining windows.
    allowed = ((speech >= SPEECH_MIN) & (music < MUSIC_HIGH) & (singing < SINGING_HIGH) & covered & active) if native else active.copy()
    # Bridge only brief low-energy pauses, never classified music/singing.
    for lo, hi, kind in _runs(np.where(allowed, "yes", "no")):
        if kind == "no" and lo > 0 and hi < count and hi - lo <= 4:
            if not native or (bool(np.all(covered[lo:hi])) and float(np.max(music[lo:hi])) < MUSIC_HIGH
                              and float(np.max(singing[lo:hi])) < SINGING_HIGH):
                allowed[lo:hi] = True

    options = []
    for lo, hi, kind in _runs(np.where(allowed, "yes", "no")):
        if kind != "yes" or (hi - lo) * HOP_SECONDS < 5:
            continue
        length = min(80, hi - lo)
        starts = list(range(lo, max(lo + 1, hi - length + 1), 10))
        if starts[-1] != hi - length:
            starts.append(hi - length)
        for start in starts:
            end = start + length
            activity = float(np.mean(active[start:end]))
            clipping = float(np.mean(features["clipped"][start:end]))
            speech_ratio = float(np.mean(speech[start:end] >= .55))
            music_ratio = float(np.mean(music[start:end] >= MUSIC_HIGH))
            singing_ratio = float(np.mean(singing[start:end] >= .30))
            if activity < .7 or clipping > .003 or (native and (
                    speech_ratio < .7 or music_ratio > .1 or singing_ratio > .1
                    or float(np.mean(music[start:end])) >= .45)):
                continue
            rank = activity - clipping * 40
            if native:
                rank += float(np.mean(speech[start:end])) - .5 * float(np.mean(music[start:end])) - float(np.mean(singing[start:end]))
            options.append((rank, start, end, speech_ratio if native else None))
    candidates = []
    for _, start, end, speech_ratio in sorted(options, key=lambda item: (-item[0], item[1])):
        left, right = start * HOP_SECONDS, min(end * HOP_SECONDS, duration)
        if any(left < item["end"] + .5 and right > item["start"] - .5 for item in candidates):
            continue
        candidates.append({
            "id": f"sample-{len(candidates) + 1}", "start": round(left, 2), "end": round(right, 2),
            "label": tr(f"{'말소리' if native else '소리'} 후보 {len(candidates) + 1}", f"{'Speech' if native else 'Sound'} candidate {len(candidates) + 1}"),
            "reasons": (
                [tr("말소리 분류가 이어짐", "Continuous speech classification"), tr("강한 음악·노래 분류가 적음", "Little strong music or singing")]
                if native else [tr("음량 기준 후보 · 말소리 여부 확인 필요", "Loudness-based candidate · check that it is speech")]
            ) + [tr("긴 침묵이 적음", "Few long silences"), tr("심한 소리 잘림이 감지되지 않음", "No heavy clipping detected")],
            "speech_fraction": round(speech_ratio, 3) if speech_ratio is not None else None,
        })
        if len(candidates) == 3:
            break
    return {"regions": regions, "candidates": candidates, "duration_seconds": round(duration, 3)}


class AppleSoundAnalysis:
    def __init__(self, settings: Settings):
        self.root = settings.storage_dir.resolve() / "bin" / "apple-sound-analysis"

    def environment(self) -> dict[str, str]:
        allowed = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "__CF_USER_TEXT_ENCODING")
        env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
        temporary = self.root / "tmp"
        temporary.mkdir(parents=True, exist_ok=True, mode=0o700)
        env.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
        return env

    def binary(self) -> Path:
        if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
            raise RuntimeError(tr("Apple 소리 분석은 Apple Silicon Mac에서 사용할 수 있습니다.", "Apple sound analysis is only available on Apple Silicon Macs."))
        source = Path(__file__).resolve().parents[2] / "scripts" / "apple_sound_analyze.swift"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
        binary = self.root / f"sound_{digest}"
        with _BUILD_LOCK:
            if binary.is_file() and os.access(binary, os.X_OK):
                return binary
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            cache = self.root / "module-cache"
            cache.mkdir(exist_ok=True)
            temporary = self.root / f".build-{uuid4().hex}"
            try:
                result = subprocess.run(
                    ["/usr/bin/swiftc", "-swift-version", "6", "-parse-as-library", "-O",
                     "-target", "arm64-apple-macos12.0", "-module-cache-path", str(cache), str(source), "-o", str(temporary)],
                    capture_output=True, text=True, check=False, timeout=90, env=self.environment(),
                )
                if result.returncode or not temporary.is_file():
                    raise RuntimeError(tr("Apple 소리 분석 실행 파일을 준비하지 못했습니다. Command Line Tools 설치를 확인해 주세요.", "Could not build the Apple sound analysis helper. Check that the Command Line Tools are installed."))
                temporary.chmod(0o700)
                temporary.replace(binary)
            finally:
                temporary.unlink(missing_ok=True)
        return binary

    def analyze(self, source: Path) -> list[dict]:
        try:
            result = subprocess.run(
                [str(self.binary())], input=json.dumps({"audio_path": str(source.resolve())}),
                capture_output=True, text=True, check=False, timeout=300, env=self.environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(tr("Apple 소리 분석을 완료하지 못했습니다. 잠시 후 다시 분석해 주세요.", "Apple sound analysis did not finish. Try again shortly.")) from exc
        if result.returncode or len(result.stdout) > 2_000_000:
            raise RuntimeError(tr("Apple 소리 분석 실행이 중단됐습니다.", "Apple sound analysis was interrupted."))
        prefix = "CLONE_VOICE_SOUND_ANALYSIS:"
        for line in reversed(result.stdout.splitlines()):
            if line.startswith(prefix):
                try:
                    payload = json.loads(line[len(prefix):])
                    if payload.get("ok") is True and all(label in payload.get("classifications", []) for label in ("speech", "music", "singing")):
                        return payload["frames"]
                except (ValueError, KeyError, TypeError):
                    break
        raise RuntimeError(tr("이 실행 환경에서 Apple의 말소리·음악 분석을 사용할 수 없습니다.", "Apple speech and music analysis is not available in this environment."))


def analyze_sample(audio_url: str, settings: Settings) -> dict:
    source = resolve_uploaded_audio(audio_url, settings)
    runtime = settings.storage_dir.resolve() / "runtime" / "sample-analysis"
    runtime.mkdir(parents=True, exist_ok=True)
    stat = source.stat()
    identity = f"{_VERSION}:{current_locale()}:{source}:{stat.st_size}:{stat.st_mtime_ns}"
    key = hashlib.sha256(identity.encode()).hexdigest()
    cache = runtime / f"{key}.json"
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
            if cached.get("engine") == "apple-sound-analysis":
                return cached
        except (OSError, ValueError, AttributeError):
            pass
    if not _ANALYSIS_SLOT.acquire(blocking=False):
        raise RuntimeError(tr("다른 오디오의 구간을 분석 중입니다. 분석이 끝난 뒤 다시 눌러 주세요.", "Another audio file is being analyzed. Try again when it finishes."))
    try:
        with tempfile.TemporaryDirectory(prefix="audio-", dir=runtime) as directory:
            wav = Path(directory) / "source.wav"
            decode_analysis_audio(source, wav)
            waveform, rate = sf.read(wav, dtype="float32")
            features = signal_features(waveform, rate)
            warning = None
            try:
                frames = AppleSoundAnalysis(settings).analyze(wav)
                _native_scores(frames, len(features["active"]), features["duration"])
            except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                frames = None
                warning = str(exc) if isinstance(exc, RuntimeError) else tr("Apple 소리 분석 준비를 완료하지 못했습니다.", "Could not set up Apple sound analysis.")
            result = recommend_regions(features, frames)
            result.update(
                engine="apple-sound-analysis" if frames is not None else "signal",
                message=tr("Apple 소리 분석으로 말소리·음악·노래 위치를 찾았습니다.", "Found speech, music and singing with Apple sound analysis.") if frames is not None else tr("음량 기준으로 소리 위치를 표시했습니다. 말소리 여부는 들어보고 확인해 주세요.", "Marked sound positions by loudness. Listen to check which are speech."),
                warnings=([warning] if warning else []) + [tr("화자 수와 음색 유사도는 판정하지 않습니다. 후보를 들어보고 한 사람의 또렷한 말소리를 선택하세요.", "Speaker count and timbre similarity are not judged. Listen to the candidates and pick a clear single speaker.")],
            )
            if frames is not None:
                temporary = runtime / f".{key}-{uuid4().hex}.json"
                try:
                    temporary.write_text(json.dumps(result, ensure_ascii=False))
                    temporary.replace(cache)
                finally:
                    temporary.unlink(missing_ok=True)
            return result
    finally:
        _ANALYSIS_SLOT.release()
