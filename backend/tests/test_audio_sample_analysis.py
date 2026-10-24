import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.api.routes import audio as audio_routes
from app.config import Settings, get_settings
from app.main import app
from app.schemas import TranscriptSegment, TranscriptSegmentsResponse
from app.services import audio_sample_analysis as analysis
from app.services.stt_service import transcribe_audio


def signal(duration, spans):
    rate = analysis.SAMPLE_RATE
    samples = np.zeros(round(duration * rate), dtype=np.float32)
    for start, end in spans:
        left, right = round(start * rate), round(end * rate)
        samples[left:right] = .15 * np.sin(2 * np.pi * 220 * np.arange(right - left) / rate)
    return samples


def frames(duration, spans, *, speech=.92, music=.12, singing=.03):
    result = []
    for start in np.arange(0, duration, .5):
        in_speech = any(left <= start < right for left, right in spans)
        result.append({"start": float(start), "end": min(float(start) + .5, duration),
                       "speech": speech if in_speech else .02, "music": music,
                       "singing": singing})
    return result


def candidates(duration, spans, **scores):
    return analysis.recommend_regions(
        analysis.signal_features(signal(duration, spans)),
        frames(duration, spans, **scores),
    )["candidates"]


def test_candidates_stay_inside_speech_after_twenty_seconds_of_silence():
    result = candidates(40, [(20, 30)])
    assert result
    assert all(20 <= item["start"] < item["end"] <= 30 for item in result)
    assert all(5 <= item["end"] - item["start"] <= 8 for item in result)


def test_mild_music_false_positives_do_not_erase_clear_speech():
    native = frames(12, [(0, 12)])
    for index, frame in enumerate(native):
        if index % 4 == 0:
            frame["music"] = .43
    result = analysis.recommend_regions(analysis.signal_features(signal(12, [(0, 12)])), native)
    assert result["candidates"]


@pytest.mark.parametrize("duration,spans", [(4.8, [(0, 4.8)]), (10.2, [(0, 4.4), (5.8, 10.2)])])
def test_short_speech_and_long_silence_are_not_stretched_into_candidates(duration, spans):
    assert candidates(duration, spans) == []


@pytest.mark.parametrize("scores", [
    {"speech": .05, "music": .95, "singing": .02},
    {"speech": .85, "music": .12, "singing": .75},
    {"speech": .85, "music": .85, "singing": .02},
])
def test_music_singing_and_loud_backing_are_not_speech_candidates(scores):
    assert candidates(12, [(0, 12)], **scores) == []


def test_repeated_clipping_is_excluded_but_an_isolated_peak_is_allowed():
    rate = analysis.SAMPLE_RATE
    samples = signal(12, [(0, 12)])
    samples[100] = 1
    assert analysis.recommend_regions(analysis.signal_features(samples), frames(12, [(0, 12)]))["candidates"]
    for second in range(12):
        samples[second * rate:second * rate + round(.05 * rate)] = 1
    assert analysis.recommend_regions(analysis.signal_features(samples), frames(12, [(0, 12)]))["candidates"] == []


def test_candidates_are_deterministic_limited_and_nonoverlapping():
    spans = [(0, 8), (12, 20), (24, 32), (36, 44)]
    first = candidates(44, spans)
    assert first == candidates(44, spans)
    assert len(first) == 3
    ordered = sorted(first, key=lambda item: item["start"])
    assert all(left["end"] + .5 <= right["start"] for left, right in zip(ordered, ordered[1:]))


def test_missing_native_coverage_is_not_treated_as_verified_speech():
    native = frames(10, [(0, 10)])
    native = [frame for frame in native if frame["start"] != 4.5]
    result = analysis.recommend_regions(analysis.signal_features(signal(10, [(0, 10)])), native)
    assert all(not (item["start"] < 5 and item["end"] > 4.5) for item in result["candidates"])


@pytest.mark.parametrize("bad_frame", [
    {"start": -1, "end": 1, "speech": .9, "music": 0, "singing": 0},
    {"start": 0, "end": 20, "speech": .9, "music": 0, "singing": 0},
    {"start": 0, "end": 1, "speech": float("nan"), "music": 0, "singing": 0},
])
def test_invalid_native_ranges_are_rejected(bad_frame):
    with pytest.raises(RuntimeError):
        analysis.recommend_regions(analysis.signal_features(signal(10, [(0, 10)])), [bad_frame])


@pytest.fixture
def sample_settings(tmp_path):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    settings.uploads_dir.mkdir(parents=True)
    sf.write(settings.uploads_dir / "sample.wav", signal(45, [(20, 32)]), analysis.SAMPLE_RATE)
    return settings


@pytest.mark.parametrize("url", [
    "https://example.com/audio.wav", "/api/files/uploads/../sample.wav",
    "/api/files/uploads/%2e%2e/sample.wav", "/api/files/voices/sample.wav",
    "/api/files/uploads/missing.wav", "/api/files/uploads/sample.wav?token=x",
])
def test_only_existing_direct_upload_urls_are_accepted(sample_settings, url):
    with pytest.raises(ValueError):
        analysis.resolve_uploaded_audio(url, sample_settings)


def test_upload_symlink_is_rejected(sample_settings):
    link = sample_settings.uploads_dir / "link.wav"
    link.symlink_to(sample_settings.uploads_dir / "sample.wav")
    with pytest.raises(ValueError):
        analysis.resolve_uploaded_audio("/api/files/uploads/link.wav", sample_settings)


def test_native_success_is_cached_and_native_failure_remains_a_labeled_fallback(sample_settings, monkeypatch):
    calls = []
    def native(self, source):
        calls.append(source)
        return frames(45, [(20, 32)])
    monkeypatch.setattr(analysis.AppleSoundAnalysis, "analyze", native)
    first = analysis.analyze_sample("/api/files/uploads/sample.wav", sample_settings)
    assert first["engine"] == "apple-sound-analysis"
    assert first["candidates"]
    assert analysis.analyze_sample("/api/files/uploads/sample.wav", sample_settings) == first
    assert len(calls) == 1

    sf.write(sample_settings.uploads_dir / "fallback.wav", signal(12, [(0, 12)]), analysis.SAMPLE_RATE)
    def unavailable(self, source):
        raise RuntimeError("Apple 소리 분석 사용 불가")
    monkeypatch.setattr(analysis.AppleSoundAnalysis, "analyze", unavailable)
    fallback = analysis.analyze_sample("/api/files/uploads/fallback.wav", sample_settings)
    assert fallback["engine"] == "signal"
    assert all(item["speech_fraction"] is None for item in fallback["candidates"])
    assert all(item["label"].startswith("소리 후보") for item in fallback["candidates"])
    assert any("사용 불가" in warning for warning in fallback["warnings"])


@pytest.fixture
def client(sample_settings):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: sample_settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_window_transcription_uses_original_coordinates_once_and_deletes_temporary_audio(client, monkeypatch):
    seen = {}
    def transcribe(path, **kwargs):
        seen.update(path=path, **kwargs)
        assert sf.info(path).duration == pytest.approx(10, abs=.01)
        return TranscriptSegmentsResponse(text="확인용 문장입니다.", segments=[
            TranscriptSegment(start=kwargs["offset_seconds"] + 1.25, end=kwargs["offset_seconds"] + 6, text="확인용 문장입니다.")
        ])
    monkeypatch.setattr(audio_routes, "get_main_transcriber", lambda: transcribe)
    response = client.post("/api/audio/sample-transcript", json={
        "audio_url": "/api/files/uploads/sample.wav", "start": 20, "end": 30,
        "provider": "apple-speech", "language": "ko",
    })
    assert response.status_code == 200, response.text
    assert response.json()["segments"] == [{"start": 21.25, "end": 26, "text": "확인용 문장입니다."}]
    assert seen["provider"] == "apple-speech" and seen["language"] == "ko"
    assert not seen["path"].exists()


@pytest.mark.parametrize("changes", [
    {"start": -1}, {"start": "NaN"}, {"end": 80}, {"end": 20},
    {"start": 40, "end": 50}, {"provider": "external"},
    {"audio_url": "https://example.com/audio.wav"},
])
def test_window_request_validation_precedes_transcription(client, monkeypatch, changes):
    monkeypatch.setattr(audio_routes, "get_main_transcriber", lambda: pytest.fail("invalid request must not transcribe"))
    request = {"audio_url": "/api/files/uploads/sample.wav", "start": 20, "end": 30}
    assert client.post("/api/audio/sample-transcript", json=request | changes).status_code == 422


def test_invalid_transcript_timestamp_is_not_returned_as_a_selectable_segment(client, monkeypatch):
    def transcribe(*args, **kwargs):
        return TranscriptSegmentsResponse(text="wrong", segments=[TranscriptSegment(start=0, end=6, text="wrong")])
    monkeypatch.setattr(audio_routes, "get_main_transcriber", lambda: transcribe)
    response = client.post("/api/audio/sample-transcript", json={"audio_url": "/api/files/uploads/sample.wav", "start": 20, "end": 30})
    assert response.status_code == 503


def test_analysis_api_returns_native_engine_and_ranges(client, monkeypatch):
    monkeypatch.setattr(analysis.AppleSoundAnalysis, "analyze", lambda self, source: frames(45, [(20, 32)]))
    response = client.post("/api/audio/sample-analysis", json={"audio_url": "/api/files/uploads/sample.wav"})
    assert response.status_code == 200
    assert response.json()["engine"] == "apple-sound-analysis"
    assert all(20 <= item["start"] < item["end"] <= 32 for item in response.json()["candidates"])


def test_whisper_receives_the_selected_language_and_offsets_once(sample_settings, monkeypatch):
    seen = {}
    def transcribe(path, **kwargs):
        seen.update(kwargs)
        return {"text": "hello", "segments": [{"start": 1, "end": 2, "text": "hello"}]}
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=lambda name, **_kw: SimpleNamespace(transcribe=transcribe)))
    result = transcribe_audio(Path("window.wav"), provider="whisper", offset_seconds=20, language="en", settings=sample_settings)
    assert seen["language"] == "en"
    assert result.segments[0].start == 21 and result.segments[0].end == 22
