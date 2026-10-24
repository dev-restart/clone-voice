from io import BytesIO
from pathlib import Path
import subprocess
from urllib.parse import quote, unquote

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import audio, files
from app.config import Settings, get_settings
from app.services import audio_export
from app.services.media_import_service import MediaAudioImport


@pytest.fixture
def exports(tmp_path):
    settings = Settings(storage_dir=tmp_path)
    app = FastAPI()
    app.include_router(files.router)
    app.include_router(audio.router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings


def write_stereo(path: Path, subtype="FLOAT"):
    sample_rate = 44_100
    time = np.arange(sample_rate) / sample_rate
    waveform = np.column_stack([
        0.2 * np.sin(2 * np.pi * 220 * time),
        0.1 * np.sin(2 * np.pi * 440 * time),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, waveform, sample_rate, subtype=subtype)


def record_temporary_directories(monkeypatch):
    directories = []
    original = audio_export.TemporaryDirectory

    def create(*args, **kwargs):
        temporary = original(*args, **kwargs)
        directories.append(Path(temporary.name))
        return temporary

    monkeypatch.setattr(audio_export, "TemporaryDirectory", create)
    return directories


@pytest.mark.parametrize("format", ["mp3", "wav"])
def test_export_preserves_stereo_and_source_and_cleans_up(exports, monkeypatch, format):
    client, settings = exports
    source = settings.outputs_dir / "완성된 커버.wav"
    write_stereo(source)
    original = source.read_bytes()
    directories = record_temporary_directories(monkeypatch)

    response = client.get(f"/api/files/outputs/{quote(source.name)}/export", params={"format": format})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == ("audio/mpeg" if format == "mp3" else "audio/wav")
    assert "attachment" in response.headers["content-disposition"]
    assert f"완성된 커버.{format}" in unquote(response.headers["content-disposition"])
    info = sf.info(BytesIO(response.content))
    waveform, sample_rate = sf.read(BytesIO(response.content), always_2d=True)
    assert sample_rate == 44_100
    assert info.channels == 2
    assert info.duration == pytest.approx(1.0, abs=0.05)
    assert not np.allclose(waveform[:, 0], waveform[:, 1], atol=0.01)
    if format == "wav":
        assert info.subtype == "FLOAT"
        assert response.content == original
        assert directories == []
    else:
        assert info.format == "MP3"
        assert directories and all(not directory.exists() for directory in directories)
    assert source.read_bytes() == original


def test_existing_mp3_is_downloaded_without_reencoding(exports, monkeypatch):
    client, settings = exports
    write_stereo(settings.outputs_dir / "sample.wav")
    encoded = client.get("/api/files/outputs/sample.wav/export")
    assert encoded.status_code == 200
    source = settings.outputs_dir / "original.mp3"
    source.write_bytes(encoded.content)
    directories = record_temporary_directories(monkeypatch)

    def unexpected_encoding(*args, **kwargs):
        pytest.fail("같은 형식의 원본 다운로드에는 ffmpeg를 실행하면 안 됩니다.")

    monkeypatch.setattr(audio_export.subprocess, "run", unexpected_encoding)

    response = client.get("/api/files/outputs/original.mp3/export?format=mp3")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content == encoded.content == source.read_bytes()
    assert sf.info(BytesIO(response.content)).format == "MP3"
    assert directories == []


@pytest.mark.parametrize("source_format", ["flac", "mp3"])
def test_other_audio_formats_are_encoded_to_pcm_wav_and_cleaned_up(exports, monkeypatch, source_format):
    client, settings = exports
    source = settings.outputs_dir / f"original.{source_format}"
    if source_format == "flac":
        write_stereo(source, subtype="PCM_24")
    else:
        write_stereo(settings.outputs_dir / "sample.wav")
        encoded = client.get("/api/files/outputs/sample.wav/export?format=mp3")
        assert encoded.status_code == 200
        source.write_bytes(encoded.content)
    original = source.read_bytes()
    directories = record_temporary_directories(monkeypatch)

    response = client.get(f"/api/files/outputs/{source.name}/export?format=wav")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert "attachment" in response.headers["content-disposition"]
    assert "original.wav" in response.headers["content-disposition"]
    info = sf.info(BytesIO(response.content))
    waveform, sample_rate = sf.read(BytesIO(response.content), always_2d=True)
    assert info.format == "WAV"
    assert info.subtype == "PCM_16"
    assert info.channels == 2
    assert info.duration == pytest.approx(1.0, abs=0.05)
    assert sample_rate == 44_100
    assert not np.allclose(waveform[:, 0], waveform[:, 1], atol=0.01)
    assert source.read_bytes() == original
    assert directories and all(not directory.exists() for directory in directories)


@pytest.mark.parametrize("bucket", ["outputs", "voices", "uploads"])
def test_default_export_is_mp3_for_each_audio_bucket(exports, bucket):
    client, settings = exports
    base = {"outputs": settings.outputs_dir, "voices": settings.voices_dir, "uploads": settings.uploads_dir}[bucket]
    write_stereo(base / "sample.wav")

    response = client.get(f"/api/files/{bucket}/sample.wav/export")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/mpeg"
    assert sf.info(BytesIO(response.content)).format == "MP3"


@pytest.mark.parametrize("isolate_voice", [True, False])
def test_media_import_audio_can_be_downloaded_as_mp3_and_original_wav(exports, monkeypatch, isolate_voice):
    client, settings = exports
    source = settings.uploads_dir / "가져온 전체 오디오.wav"

    def import_source(url, settings, isolate_voice=False):
        write_stereo(source)
        return MediaAudioImport(platform="youtube", title="가져온 음성 또는 음악", webpage_url=url,
                                duration_seconds=1, audio_path=source, voice_isolated=isolate_voice)

    monkeypatch.setattr(audio, "get_media_importer", lambda: import_source)
    imported = client.post("/api/audio/media-import", json={
        "url": "https://www.youtube.com/watch?v=audio-source", "isolate_voice": isolate_voice,
    })
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["voice_isolated"] is isolate_voice
    original = source.read_bytes()
    export_path = f"/api/files/uploads/{quote(source.name)}/export"

    mp3 = client.get(export_path, params={"format": "mp3"})
    assert mp3.status_code == 200
    assert mp3.headers["content-type"] == "audio/mpeg"
    assert sf.info(BytesIO(mp3.content)).format == "MP3"
    assert sf.info(BytesIO(mp3.content)).duration == pytest.approx(1, abs=.05)
    assert sf.info(BytesIO(mp3.content)).channels == 2
    assert "attachment" in mp3.headers["content-disposition"]
    assert payload["audio_url"] == f"/api/files/uploads/{source.name}"
    wav = client.get(export_path, params={"format": "wav"})
    assert wav.status_code == 200
    assert wav.content == original == source.read_bytes()


def test_original_file_playback_and_download_remain_unchanged(exports):
    client, settings = exports
    source = settings.outputs_dir / "sample.wav"
    write_stereo(source)

    inline = client.get("/api/files/outputs/sample.wav")
    download = client.get("/api/files/outputs/sample.wav?download=true")

    assert inline.content == download.content == source.read_bytes()
    assert "inline" in inline.headers["content-disposition"]
    assert "attachment" in download.headers["content-disposition"]


@pytest.mark.parametrize("url,status", [
    ("/api/files/unknown/sample.wav/export", 404),
    ("/api/files/outputs/missing.wav/export", 404),
    ("/api/files/outputs/sample.wav/export?format=flac", 422),
    ("/api/files/outputs/settings.json/export", 422),
])
def test_export_rejects_missing_and_unsupported_files(exports, url, status):
    client, settings = exports
    write_stereo(settings.outputs_dir / "sample.wav")
    (settings.outputs_dir / "settings.json").write_text("{}")

    assert client.get(url).status_code == status


def test_export_rejects_symlinks_outside_bucket(exports, tmp_path):
    client, settings = exports
    source = tmp_path / "private.wav"
    write_stereo(source)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    (settings.outputs_dir / "outside.wav").symlink_to(source)

    assert client.get("/api/files/outputs/outside.wav/export").status_code == 404


@pytest.mark.parametrize("failure", [
    FileNotFoundError("ffmpeg"),
    subprocess.CalledProcessError(1, "ffmpeg"),
    subprocess.TimeoutExpired("ffmpeg", 120),
])
def test_export_failure_is_actionable_and_removes_temporary_files(exports, monkeypatch, failure):
    client, settings = exports
    source = settings.outputs_dir / "sample.wav"
    write_stereo(source)
    original = source.read_bytes()
    directories = record_temporary_directories(monkeypatch)

    def fail(*args, **kwargs):
        Path(args[0][-1]).write_bytes(b"partial audio")
        raise failure

    monkeypatch.setattr(audio_export.subprocess, "run", fail)

    response = client.get("/api/files/outputs/sample.wav/export")

    assert response.status_code == 503
    assert "내보내기에 실패" in response.json()["detail"]
    assert source.read_bytes() == original
    assert directories and all(not directory.exists() for directory in directories)


def test_export_with_no_encoder_output_fails_and_cleans_up(exports, monkeypatch):
    client, settings = exports
    write_stereo(settings.outputs_dir / "sample.wav")
    directories = record_temporary_directories(monkeypatch)
    monkeypatch.setattr(audio_export.subprocess, "run", lambda *args, **kwargs: None)

    response = client.get("/api/files/outputs/sample.wav/export")

    assert response.status_code == 503
    assert directories and all(not directory.exists() for directory in directories)
