from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings, get_settings
from app.db.models import DbConversionJob
from app.db.session import session_scope
from app.main import app
from app.schemas import (
    ContentItem,
    ContentResult,
    ModelCapabilities,
    RuntimeModelStatus,
    VoiceProfile,
)
from app.services.content_store import ContentStore
from app.services.model_router import EngineOutput
from app.services.voice_store import VoiceStore


class AvailableVoiceConversionAdapter:
    model_id = "soulx-singer"
    label = "SoulX-Singer"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def status(self):
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider="test",
            status="available",
            enabled=True,
            loaded=True,
            capabilities=ModelCapabilities(
                voice_conversion=True, singing_voice_conversion=True
            ),
        )

    def convert_voice(self, source_audio: Path, target_voice, **kwargs):
        output = self.output_dir / "voice-conversion-output.wav"
        write_wav(output, duration=0.8)
        return EngineOutput(
            path=output, duration_seconds=0.8, transcript="captured transcript"
        )


class SingleAdapterRouter:
    def __init__(self, adapter):
        self.adapter = adapter

    def get(self, model_id: str | None, purpose: str = "tts"):
        return self.adapter


def write_wav(path: Path, duration: float = 0.5, sample_rate: int = 24000) -> None:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, waveform, sample_rate)


def wav_bytes(duration: float = 0.5) -> bytes:
    buffer = BytesIO()
    t = np.linspace(0, duration, int(24000 * duration), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    sf.write(buffer, waveform, 24000, format="WAV")
    return buffer.getvalue()


def asset_client(tmp_path: Path) -> tuple[TestClient, Settings]:
    app.dependency_overrides.clear()
    settings = Settings(
        storage_dir=tmp_path,
        voxcpm_enabled=False,
        soulx_singer_enabled=False,
        stable_audio_sfx_enabled=False,
        default_tts_model="voxcpm",
        default_vc_model="soulx-singer",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), settings


def test_assets_catalog_returns_registered_voices_generated_files_and_orphans(
    tmp_path: Path,
):
    client, settings = asset_client(tmp_path)

    voice_audio = settings.voices_dir / "voice-reference.wav"
    source_audio = settings.uploads_dir / "voice-source.wav"
    tts_output = settings.outputs_dir / "tts-result.wav"
    cover_output = settings.outputs_dir / "cover-result.wav"
    orphan_output = settings.outputs_dir / "rain-sfx.wav"
    duplicate_cover = settings.outputs_dir / "duplicate-cover.wav"

    write_wav(voice_audio, duration=0.6)
    write_wav(source_audio, duration=0.7)
    write_wav(tts_output, duration=1.1)
    write_wav(cover_output, duration=1.4)
    write_wav(orphan_output, duration=0.9)
    write_wav(duplicate_cover, duration=1.0)

    voice_store = VoiceStore(settings.voices_dir, settings)
    voice_store.save(
        VoiceProfile(
            id="voice-1",
            name="Narrator",
            transcript="reference transcript",
            audio_path=str(voice_audio),
            audio_url=f"/api/files/voices/{voice_audio.name}",
            source_audio_path=str(source_audio),
            source_audio_url=f"/api/files/uploads/{source_audio.name}",
            trim_start=0.25,
            trim_end=2.75,
            created_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
        )
    )

    content_store = ContentStore(settings.contents_dir, settings)
    content_store.save(
        ContentItem(
            id="content-1",
            title="Launch script",
            source_text="제품 소개 문장",
            results=[
                ContentResult(
                    id="result-1",
                    language="ko",
                    text="안녕하세요. 제품 소개입니다.",
                    voice_id="voice-1",
                    voice_name="Narrator",
                    model_id="voxcpm",
                    audio_url=f"/api/files/outputs/{tts_output.name}",
                    duration_seconds=1.1,
                    created_at=datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc),
                ),
                ContentResult(
                    id="result-duplicate",
                    language="ko",
                    text="중복 파일",
                    voice_id="voice-1",
                    voice_name="Narrator",
                    model_id="voxcpm",
                    audio_url=f"/api/files/outputs/{duplicate_cover.name}",
                    duration_seconds=1.0,
                    created_at=datetime(2026, 8, 12, 10, 30, tzinfo=timezone.utc),
                ),
            ],
        )
    )

    with session_scope(settings) as session:
        session.add(
            DbConversionJob(
                id="job-1",
                model_id="soulx-singer",
                source_audio_path=str(settings.uploads_dir / "cover-input.wav"),
                target_voice_id="voice-1",
                output_audio_url=f"/api/files/outputs/{cover_output.name}",
                transcript="captured transcript",
                created_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
            )
        )
        session.add(
            DbConversionJob(
                id="job-duplicate",
                model_id="soulx-singer",
                source_audio_path=str(settings.uploads_dir / "duplicate-input.wav"),
                target_voice_id="voice-1",
                output_audio_url=f"/api/files/outputs/{duplicate_cover.name}",
                transcript="duplicate transcript",
                created_at=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc),
            )
        )

    response = client.get("/api/assets")

    assert response.status_code == 200
    payload = response.json()
    assert [voice["id"] for voice in payload["registered_voices"]] == ["voice-1"]
    registered = payload["registered_voices"][0]
    assert registered["kind"] == "registered-voice"
    assert registered["voice_name"] == "Narrator"
    assert registered["source_audio_url"] == f"/api/files/uploads/{source_audio.name}"
    assert registered["trim_start"] == 0.25
    assert registered["trim_end"] == 2.75
    assert registered["available"] is True
    assert registered["duration_seconds"] >= 0.5

    generated = {item["id"]: item for item in payload["generated_files"]}
    assert set(generated) == {
        "job-1",
        "result-1",
        "result-duplicate",
        f"orphan:{orphan_output.name}",
    }
    ai_cover = generated["job-1"]
    assert ai_cover["kind"] == "ai-cover"
    assert ai_cover["voice_id"] == "voice-1"
    assert ai_cover["voice_name"] == "Narrator"
    assert ai_cover["model_id"] == "soulx-singer"
    assert ai_cover["source_title"] == "cover-input"
    assert ai_cover["transcript"] == "captured transcript"
    assert ai_cover["available"] is True
    tts_result = generated["result-1"]
    assert tts_result["kind"] == "tts"
    assert tts_result["title"] == "Launch script"
    assert tts_result["voice_name"] == "Narrator"
    assert tts_result["duration_seconds"] == 1.1
    orphan = generated[f"orphan:{orphan_output.name}"]
    assert orphan["kind"] == "sound-effect"
    assert orphan["voice_id"] is None
    assert orphan["available"] is True


def test_file_route_supports_attachment_download(tmp_path: Path):
    client, settings = asset_client(tmp_path)
    target = settings.outputs_dir / "download-me.wav"
    write_wav(target, duration=0.4)

    response = client.get(f"/api/files/outputs/{target.name}?download=true")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(
        f'attachment; filename="{target.name}"'
    )


def test_voice_conversion_response_includes_job_metadata_and_jobs_endpoint_returns_all_models(
    tmp_path: Path,
):
    client, settings = asset_client(tmp_path)
    adapter = AvailableVoiceConversionAdapter(settings.outputs_dir)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(
        adapter
    )

    voice_response = client.post(
        "/api/voices",
        data={"name": "Singer", "transcript": "Reference text"},
        files={"audio": ("voice.wav", wav_bytes(), "audio/wav")},
    )
    assert voice_response.status_code == 201
    voice_id = voice_response.json()["id"]
    assert "audio_path" not in voice_response.json()
    assert "source_audio_path" not in voice_response.json()

    response = client.post(
        "/api/voice-conversion",
        data={"voice_id": voice_id, "conversion_mode": "singing"},
        files={"audio": ("source.wav", wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"]
    assert payload["created_at"]

    with session_scope(settings) as session:
        session.add(
            DbConversionJob(
                id="job-manual",
                model_id="other-cover-model",
                source_audio_path=str(settings.uploads_dir / "manual-input.wav"),
                target_voice_id=voice_id,
                output_audio_url="/api/files/outputs/manual-cover.wav",
                created_at=datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc),
            )
        )

    jobs_response = client.get("/api/voice-conversion/jobs")

    assert jobs_response.status_code == 200
    jobs = jobs_response.json()
    assert len(jobs) == 2
    assert {job["id"] for job in jobs} == {payload["job_id"], "job-manual"}
    assert {job["model_id"] for job in jobs} == {"other-cover-model", "soulx-singer"}
    assert all("source_audio_path" not in job for job in jobs)
    generated_job = next(job for job in jobs if job["id"] == payload["job_id"])
    assert generated_job["source_audio_url"].startswith("/api/files/uploads/")
