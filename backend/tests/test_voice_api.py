import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app import main as main_module
from app.api.routes import voice_conversion as voice_conversion_routes
from app.api.routes import sound_effects as sound_effect_routes
from app.main import app
from app.schemas import ModelCapabilities, RuntimeModelStatus, TranscriptSegment, TranscriptSegmentsResponse
from app.services.model_router import EngineOutput, ModelRouter, ModelUnavailableError
from app.services.omnivoice_service import MockVoiceEngine, combine_omnivoice_instruct, get_voice_engine, language_code_to_omnivoice_language, normalize_omnivoice_instruct
from app.services.progress import progress_events
from app.services.sound_effect_prompt_service import SoundEffectPromptPlan
from app.services.media_import_service import MediaAudioImport, media_dlp_common_options, normalize_media_url
from app.services.ai_text_provider_service import AiTextProviderService

class CapturingVoiceEngine(MockVoiceEngine):
    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self.last_voice = None
        self.last_kwargs = None

    def generate(self, **kwargs):
        self.last_voice = kwargs.get("voice")
        self.last_kwargs = kwargs
        return super().generate(**kwargs)


class EmptyVoiceEngine(MockVoiceEngine):
    def generate(self, **kwargs):
        output = self.output_dir / "empty.wav"
        sf.write(output, np.array([], dtype=np.float32), 24000)
        return output, 0.0


class AvailableTTSAdapter:
    model_id = "fake-tts"
    label = "Fake TTS"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.calls = []

    def status(self):
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider="test",
            status="available",
            enabled=True,
            loaded=True,
            capabilities=ModelCapabilities(tts=True, voice_clone_tts=True),
        )

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        duration = 0.25
        sample_rate = 24000
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        waveform = (0.08 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"fake-{len(self.calls)}.wav"
        sf.write(output, waveform, sample_rate)
        return EngineOutput(path=output, duration_seconds=duration)


class AvailableVoxCPMAdapter(AvailableTTSAdapter):
    model_id = "voxcpm"
    label = "VoxCPM2"


class AvailableVoiceConversionAdapter:
    model_id = "soulx-singer"
    label = "SoulX-Singer"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.calls = []

    def status(self):
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider="test",
            status="available",
            enabled=True,
            loaded=True,
            capabilities=ModelCapabilities(voice_conversion=True, singing_voice_conversion=True),
        )

    def convert_voice(self, source_audio: Path, target_voice, **kwargs):
        self.calls.append({"source_audio": source_audio, "target_voice": target_voice, **kwargs})
        duration = 0.5
        sample_rate = 24000
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        waveform = (0.08 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / "soulx-singer-output.wav"
        sf.write(output, waveform, sample_rate)
        return EngineOutput(path=output, duration_seconds=duration, transcript="captured transcript")

class AvailableSoundEffectAdapter:
    model_id = "stable-audio-sfx"
    label = "Stable Audio 3 SFX"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.calls = []

    def status(self):
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider="test",
            status="available",
            enabled=True,
            loaded=True,
            sample_rate=44100,
            capabilities=ModelCapabilities(sound_effect_generation=True),
        )

    def generate_sound_effect(self, **kwargs):
        self.calls.append(kwargs)
        duration = float(kwargs["duration_seconds"])
        sample_rate = 44100
        waveform = np.zeros((int(sample_rate * duration), 2), dtype=np.float32)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / f"sfx-{len(self.calls)}.wav"
        sf.write(output, waveform, sample_rate)
        return EngineOutput(path=output, duration_seconds=duration)


class SingleAdapterRouter:
    def __init__(self, adapter):
        self.adapter = adapter

    def get(self, model_id: str | None, purpose: str = "tts"):
        return self.adapter


def sample_wav_bytes() -> bytes:
    buffer = BytesIO()
    sample_rate = 24000
    t = np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(buffer, waveform, sample_rate, format="WAV")
    return buffer.getvalue()


def client_with_mock_engine(tmp_path: Path, engine: MockVoiceEngine | None = None) -> TestClient:
    app.dependency_overrides.clear()
    test_settings = Settings(
        storage_dir=tmp_path,
        voxcpm_enabled=False,
        soulx_singer_enabled=False,
        stable_audio_sfx_enabled=False,
        default_tts_model="voxcpm",
        default_vc_model="soulx-singer",
    )
    selected_engine = engine or MockVoiceEngine(output_dir=test_settings.outputs_dir)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_voice_engine] = lambda: selected_engine
    return TestClient(app)


def test_health_reports_model_status(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model"]["engine"] == "voxcpm"


def test_ai_provider_catalog_and_selection_endpoint(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    monkeypatch.setattr(
        AiTextProviderService,
        "_local_models",
        lambda self: ([{"id": "translategemma:12b", "label": "translategemma:12b"}], True, "connected"),
    )
    monkeypatch.setattr(AiTextProviderService, "_chatgpt_status", lambda self: (True, "connected", "/bin/codex"))
    monkeypatch.setattr(AiTextProviderService, "_kimi_status", lambda self: (True, "connected", "/bin/kimi"))
    monkeypatch.setattr(AiTextProviderService, "_kimi_models", lambda self: [{"id": "k3", "label": "Kimi K3"}])

    catalog_response = client.get("/api/ai/providers")
    selection_response = client.put(
        "/api/ai/providers/selection",
        json={"provider_id": "chatgpt", "model_id": "gpt-5.6-luna"},
    )

    assert catalog_response.status_code == 200
    assert [provider["id"] for provider in catalog_response.json()["providers"]] == ["local", "chatgpt", "kimi", "apple"]
    assert selection_response.status_code == 200
    assert selection_response.json()["selection"] == {
        "provider_id": "chatgpt",
        "model_id": "gpt-5.6-luna",
    }


def test_models_endpoint_reports_unavailable_when_real_engine_is_disabled(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    models = {model["id"]: model for model in payload["models"]}
    assert payload["default_tts_model"] == "voxcpm"
    assert payload["default_vc_model"] == "soulx-singer"
    assert sorted(models) == ["soulx-singer", "stable-audio-sfx", "voxcpm"]
    assert models["voxcpm"]["status"] == "unavailable"
    assert models["soulx-singer"]["status"] == "unavailable"
    assert payload["model_preferences"]["voxcpm"]["enabled"] is True
    assert (tmp_path / "clone_voice.db").exists()


def test_models_endpoint_only_exposes_registered_models(tmp_path: Path):
    app.dependency_overrides.clear()
    test_settings = Settings(
        storage_dir=tmp_path,
        registered_models=["voxcpm", "soulx-singer"],
        default_tts_model="voxcpm",
        default_vc_model="soulx-singer",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)

    response = client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    assert [model["id"] for model in payload["models"]] == ["voxcpm", "soulx-singer"]
    assert sorted(payload["model_preferences"]) == ["soulx-singer", "voxcpm"]
    assert payload["default_tts_model"] == "voxcpm"
    assert payload["default_vc_model"] == "soulx-singer"


def test_model_router_rejects_unregistered_model(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path, registered_models=["voxcpm"], default_tts_model="voxcpm")
    router = ModelRouter(settings)

    assert [model.id for model in router.list()] == ["voxcpm"]
    assert router.get(None).model_id == "voxcpm"
    with pytest.raises(ModelUnavailableError):
        router.get("soulx-singer")


def test_model_router_falls_back_when_configured_default_is_not_registered(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path, registered_models=["voxcpm"], default_tts_model="soulx-singer")
    router = ModelRouter(settings)

    assert router.get(None).model_id == "voxcpm"


def test_storage_locations_can_be_overridden(tmp_path: Path):
    settings = Settings(
        storage_dir=tmp_path / "state",
        voice_dir=tmp_path / "registered-voices",
        upload_dir=tmp_path / "incoming",
        output_dir=tmp_path / "generated",
        content_dir=tmp_path / "content-files",
    )

    assert settings.resolved_database_url == f"sqlite:///{tmp_path / 'state' / 'clone_voice.db'}"
    assert settings.voices_dir == tmp_path / "registered-voices"
    assert settings.uploads_dir == tmp_path / "incoming"
    assert settings.outputs_dir == tmp_path / "generated"
    assert settings.contents_dir == tmp_path / "content-files"


def test_model_preferences_are_persisted_in_sqlite(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.put(
        "/api/models/preferences",
        json={
            "default_tts_model": "voxcpm",
            "default_vc_model": "soulx-singer",
            "model_preferences": {
                "voxcpm": {"id": "voxcpm", "enabled": True, "order": 30},
                "soulx-singer": {"id": "soulx-singer", "enabled": True, "order": 20},
                "stable-audio-sfx": {"id": "stable-audio-sfx", "enabled": False, "order": 10},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_tts_model"] == "voxcpm"
    assert payload["default_vc_model"] == "soulx-singer"
    assert payload["model_preferences"]["stable-audio-sfx"]["enabled"] is False
    assert payload["model_preferences"]["stable-audio-sfx"]["order"] == 10
    assert (tmp_path / "clone_voice.db").exists()

    reloaded_client = client_with_mock_engine(tmp_path)
    reloaded = reloaded_client.get("/api/models").json()
    assert reloaded["default_tts_model"] == "voxcpm"
    assert reloaded["default_vc_model"] == "soulx-singer"
    assert reloaded["model_preferences"]["stable-audio-sfx"]["enabled"] is False


def test_model_preferences_reject_disabling_every_tts_model(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.put(
        "/api/models/preferences",
        json={
            "default_tts_model": "voxcpm",
            "model_preferences": {
                "voxcpm": {"id": "voxcpm", "enabled": False, "order": 10},
                "soulx-singer": {"id": "soulx-singer", "enabled": True, "order": 20},
                "stable-audio-sfx": {"id": "stable-audio-sfx", "enabled": True, "order": 30},
            },
        },
    )

    assert response.status_code == 422


def test_model_preferences_reject_non_vc_default_model(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.put(
        "/api/models/preferences",
        json={
            "default_tts_model": "voxcpm",
            "default_vc_model": "voxcpm",
            "model_preferences": {
                "voxcpm": {"id": "voxcpm", "enabled": True, "order": 10},
                "soulx-singer": {"id": "soulx-singer", "enabled": True, "order": 20},
                "stable-audio-sfx": {"id": "stable-audio-sfx", "enabled": True, "order": 30},
            },
        },
    )

    assert response.status_code == 422
    assert "voice conversion" in response.json()["detail"]


def test_model_preferences_reject_disabling_every_vc_model(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.put(
        "/api/models/preferences",
        json={
            "default_tts_model": "voxcpm",
            "default_vc_model": "soulx-singer",
            "model_preferences": {
                "voxcpm": {"id": "voxcpm", "enabled": True, "order": 10},
                "soulx-singer": {"id": "soulx-singer", "enabled": False, "order": 20},
                "stable-audio-sfx": {"id": "stable-audio-sfx", "enabled": True, "order": 30},
            },
        },
    )

    assert response.status_code == 422
    assert "voice-conversion" in response.json()["detail"]


def test_voice_can_be_registered_from_uploaded_audio(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post(
        "/api/voices",
        data={"name": "Sample Korean Voice", "transcript": "안녕하세요. 테스트 목소리입니다."},
        files={"audio": ("sample.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"]
    assert payload["name"] == "Sample Korean Voice"
    assert payload["transcript"] == "안녕하세요. 테스트 목소리입니다."
    assert payload["audio_url"].startswith("/api/files/voices/")

    list_response = client.get("/api/voices")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == payload["id"]


def test_voice_metadata_and_avatar_can_be_updated(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Original Voice", "transcript": "처음 대본"},
        files={"audio": ("sample.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    metadata_response = client.patch(
        f"/api/voices/{voice['id']}",
        json={"name": "Edited Voice", "description": "밝고 또렷한 안내 목소리", "transcript": "수정된 대본"},
    )

    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["name"] == "Edited Voice"
    assert metadata["description"] == "밝고 또렷한 안내 목소리"
    assert metadata["transcript"] == "수정된 대본"

    avatar_response = client.post(
        f"/api/voices/{voice['id']}/avatar",
        files={"avatar": ("avatar.png", b"\x89PNG\r\n\x1a\navatar", "image/png")},
    )

    assert avatar_response.status_code == 200
    avatar = avatar_response.json()
    assert avatar["avatar"].startswith("/api/files/uploads/")
    assert (tmp_path / "uploads" / Path(avatar["avatar"]).name).exists()


def test_voice_transcript_endpoint_can_use_selected_range(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    voice_response = client.post(
        "/api/voices",
        data={"name": "Transcript Voice", "transcript": ""},
        files={"audio": ("sample.wav", sample_wav_bytes(), "audio/wav")},
    )
    voice_id = voice_response.json()["id"]
    calls = []

    def fake_transcribe(path: Path, offset_seconds: float = 0, **kwargs):
        calls.append((path, offset_seconds))
        return TranscriptSegmentsResponse(
            segments=[TranscriptSegment(start=offset_seconds, end=offset_seconds + 0.2, text="테스트 구간")],
            text="테스트 구간",
        )

    monkeypatch.setattr(main_module, "transcribe_with_segments", fake_transcribe)

    response = client.get(f"/api/voices/{voice_id}/transcript-segments?trim_start=0.1&trim_end=0.4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "테스트 구간"
    assert payload["segments"][0]["start"] == 0.1
    assert calls[0][1] == 0.1


def test_uploaded_audio_transcript_endpoint_can_use_selected_range(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    calls = []

    def fake_transcribe(path: Path, offset_seconds: float = 0, **kwargs):
        calls.append((path, offset_seconds))
        return TranscriptSegmentsResponse(
            segments=[TranscriptSegment(start=offset_seconds, end=offset_seconds + 0.2, text="업로드 구간")],
            text="업로드 구간",
        )

    monkeypatch.setattr(main_module, "transcribe_with_segments", fake_transcribe)

    response = client.post(
        "/api/audio/transcript-segments",
        data={"trim_start": "0.1", "trim_end": "0.4"},
        files={"audio": ("sample.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "업로드 구간"
    assert payload["segments"][0]["start"] == 0.1
    assert calls[0][1] == 0.1


def test_upload_audio_source_persists_original_file(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post(
        "/api/audio/uploads",
        files={"audio": ("source.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audio_url"].startswith("/api/files/uploads/")
    assert payload["filename"] == "source.wav"
    assert "audio_path" not in payload
    assert any((tmp_path / "uploads").iterdir())


def test_media_import_endpoint_returns_uploaded_audio_url(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    imported_audio = tmp_path / "uploads" / "youtube.wav"
    imported_audio.parent.mkdir(parents=True, exist_ok=True)
    imported_audio.write_bytes(sample_wav_bytes())

    def fake_import(url: str, settings: Settings, isolate_voice: bool = False):
        assert isolate_voice is True
        return MediaAudioImport(
            platform="instagram",
            title="샘플 영상",
            webpage_url=url,
            duration_seconds=12.5,
            audio_path=imported_audio,
            voice_isolated=isolate_voice,
        )

    monkeypatch.setattr(main_module, "import_media_audio", fake_import)

    response = client.post("/api/audio/media-import", json={"url": "https://www.instagram.com/reel/sample/", "isolate_voice": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["platform"] == "instagram"
    assert payload["title"] == "샘플 영상"
    assert payload["audio_url"] == "/api/files/uploads/youtube.wav"
    assert payload["duration_seconds"] == 12.5
    assert "audio_path" not in payload
    assert payload["voice_isolated"] is True


def test_media_url_normalizer_accepts_youtube_video_and_shorts_urls():
    watch = normalize_media_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12")
    shorts = normalize_media_url("https://www.youtube.com/shorts/WuW8V7US-0o?si=share")
    short_mobile = normalize_media_url("https://m.youtube.com/shorts/WuW8V7US-0o")
    short_link = normalize_media_url("https://youtu.be/WuW8V7US-0o?feature=shared")

    assert watch.platform == "youtube"
    assert watch.kind == "video"
    assert watch.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert shorts.kind == "shorts"
    assert shorts.url == "https://www.youtube.com/shorts/WuW8V7US-0o"
    assert short_mobile.url == "https://www.youtube.com/shorts/WuW8V7US-0o"
    assert short_link.url == "https://www.youtube.com/watch?v=WuW8V7US-0o"


def test_media_url_normalizer_accepts_instagram_post_and_reel_urls():
    post = normalize_media_url("https://www.instagram.com/p/ABC_def-12/?utm_source=share")
    reel = normalize_media_url("instagram.com/reels/XYZ_98765/")

    assert post.platform == "instagram"
    assert post.kind == "post"
    assert post.url == "https://www.instagram.com/p/ABC_def-12/"
    assert reel.kind == "reel"
    assert reel.url == "https://www.instagram.com/reel/XYZ_98765/"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/abcdef",
        "https://www.instagram.com/some-profile/",
        "https://www.instagram.com/explore/",
        "https://www.youtube.com/playlist?list=abcdef",
    ],
)
def test_media_url_normalizer_rejects_unsupported_or_collection_urls(url: str):
    with pytest.raises(RuntimeError):
        normalize_media_url(url)


def test_media_import_options_use_configured_cookie_file(tmp_path: Path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    settings = Settings(storage_dir=tmp_path / "storage", media_import_cookie_file=cookie_file)

    options = media_dlp_common_options(settings)

    assert options["cookiefile"] == str(cookie_file)
    assert options["noplaylist"] is True


def test_text_generation_with_registered_voice_returns_audio_file(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/generate",
        json={"text": "오늘은 음성 복제 테스트를 합니다.", "voice_id": voice["id"], "speed": 1.0, "num_step": 16},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "오늘은 음성 복제 테스트를 합니다."
    assert payload["voice_id"] == voice["id"]
    assert payload["audio_url"].startswith("/api/files/outputs/")
    assert (tmp_path / "outputs" / Path(payload["audio_url"]).name).exists()


def test_tts_endpoint_rejects_disabled_real_model(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post("/api/tts", json={"text": "새 라우터로 생성합니다.", "model_id": "voxcpm", "language": "ko"})

    assert response.status_code == 409
    assert "CLONE_VOICE_VOXCPM_ENABLED" in response.json()["detail"]


def test_generate_endpoint_can_route_to_selected_tts_adapter(tmp_path: Path):
    adapter = AvailableTTSAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)

    response = client.post(
        "/api/generate",
        json={"text": "선택 모델로 생성합니다.", "model_id": "fake-tts", "language": "ko", "tone_prompt": "차분하게"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_id"] == "fake-tts"
    assert adapter.calls[0]["text"] == "선택 모델로 생성합니다."
    assert adapter.calls[0]["instruct"] == "low pitch, korean accent"


def test_tts_endpoint_keeps_output_normalization_as_postprocess_only(tmp_path: Path):
    adapter = AvailableTTSAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)

    response = client.post(
        "/api/tts",
        json={"text": "후처리 옵션은 모델에 직접 넘기지 않습니다.", "model_id": "fake-tts", "normalize_output": True},
    )

    assert response.status_code == 200
    assert adapter.calls
    assert "normalize_output" not in adapter.calls[0]


def test_tts_endpoint_accepts_json_narration_script(tmp_path: Path):
    adapter = AvailableTTSAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)

    response = client.post(
        "/api/tts",
        json={
            "text": json.dumps(
                [
                    {"text": "첫 문장입니다.", "tone": "calm", "speed": 0.95, "pitch": "low", "pause_after_ms": 700},
                    {"text": "두 번째 문장입니다.", "tone": "bright", "speed": 1.05, "pause_after_ms": 0},
                ],
                ensure_ascii=False,
            ),
            "model_id": "fake-tts",
            "language": "ko",
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audio_url"].startswith("/api/files/outputs/")
    assert len(adapter.calls) == 2
    assert adapter.calls[0]["text"] == "첫 문장입니다."
    assert adapter.calls[0]["speed"] == 0.95
    assert "low pitch" in adapter.calls[0]["instruct"]
    assert payload["duration_seconds"] >= 1.1


def test_tts_endpoint_with_voxcpm_auto_chunks_keeps_voice_and_style_consistent(tmp_path: Path):
    adapter = AvailableVoxCPMAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    voice = client.post(
        "/api/voices",
        data={"name": "Kim voice", "transcript": "기준 목소리입니다."},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()
    script = (
        "여기 한 남자가 있습니다. "
        "오랫동안 코드를 만져온 베테랑, 머릿속엔 이미 완성된 앱의 설계도가 가득하죠. "
        "그가 만들려는 건 뜻밖에도 상장입니다. "
        "책을 사고 유튜브를 뒤져봐도, 이론은 구름 위를 떠다니고 예제는 내 상황과 맞지 않습니다. "
    ) * 8

    response = client.post(
        "/api/tts",
        json={
            "text": script,
            "model_id": "voxcpm",
            "voice_id": voice["id"],
            "language": "ko",
            "tone_prompt": "흥미진진하게",
            "style_prompt": "유튜브홍보영상 스타일로",
            "speed": 0.8,
            "num_step": 16,
            "guidance_scale": 1.7,
            "denoise": False,
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    assert len(adapter.calls) > 1
    assert "".join(call["text"].replace(" ", "") for call in adapter.calls) == script.strip().replace(" ", "")
    assert all(call["voice"].id == voice["id"] for call in adapter.calls)
    assert len({call["instruct"] for call in adapter.calls}) == 1
    assert "excited and engaging tone" in adapter.calls[0]["instruct"]
    assert "energetic promotional video narration" in adapter.calls[0]["instruct"]
    assert all(call["language"] == "ko" for call in adapter.calls)
    assert all(call["speed"] == 0.8 for call in adapter.calls)
    assert all(call["duration"] is None for call in adapter.calls)
    assert all(call["num_step"] == 16 for call in adapter.calls)
    assert all(call["guidance_scale"] == 1.7 for call in adapter.calls)
    assert all(call["denoise"] is False for call in adapter.calls)
    assert response.json()["text"] == script.strip()


def test_story_studio_generates_segments_with_individual_voice_and_language(tmp_path: Path):
    adapter = AvailableTTSAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    korean_voice = client.post(
        "/api/voices",
        data={"name": "Korean Narrator", "transcript": "안녕하세요."},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/story-studio/generate",
        json={
            "title": "Story mix",
            "default_model_id": "fake-tts",
            "normalize_output": False,
            "segments": [
                {
                    "id": "one",
                    "text": "There was a boy who dreamed of flying.",
                    "language": "en",
                    "voice_id": None,
                    "tone_prompt": "high pitch",
                    "accent": "british accent",
                    "speed": 1.1,
                    "pause_after_ms": 500,
                },
                {
                    "id": "two",
                    "text": "그는 직접 만든 날개로 날고 싶었습니다.",
                    "language": "ko",
                    "voice_id": korean_voice["id"],
                    "tone_prompt": "차분하게",
                    "speed": 0.9,
                    "pause_after_ms": 0,
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Story mix"
    assert payload["audio_url"].startswith("/api/files/outputs/")
    assert payload["duration_seconds"] >= 1.0
    assert len(payload["segments"]) == 2
    assert payload["segments"][0]["effective_instruct"] == "high pitch, british accent"
    assert payload["segments"][1]["voice_name"] == "Korean Narrator"
    assert len(adapter.calls) == 2
    assert adapter.calls[0]["language"] == "en"
    assert adapter.calls[1]["voice"].id == korean_voice["id"]


def test_sound_effect_endpoint_generates_reproducible_variations(tmp_path: Path):
    adapter = AvailableSoundEffectAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)

    response = client.post(
        "/api/sound-effects/generate",
        json={
            "prompt": "A wooden door closes once",
            "negative_prompt": "speech, music",
            "duration_seconds": 2.5,
            "auto_duration": False,
            "steps": 8,
            "guidance_scale": 3,
            "seed": 120,
            "variations": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["seed"] for item in payload["results"]] == [120, 121]
    assert all(item["audio_url"].startswith("/api/files/outputs/") for item in payload["results"])
    assert len(adapter.calls) == 2
    assert all(call["prompt"] == "A wooden door closes once" for call in adapter.calls)
    assert all(call["duration_seconds"] == 2.5 for call in adapter.calls)
    assert payload["plan"]["duration_mode"] == "manual"


def test_sound_effect_endpoint_uses_planned_english_prompt_and_duration(tmp_path: Path, monkeypatch):
    adapter = AvailableSoundEffectAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)

    monkeypatch.setattr(
        sound_effect_routes,
        "plan_sound_effect_prompt",
        lambda *args, **kwargs: SoundEffectPromptPlan(
            source_prompt="조용한 방에서 나무 문이 한 번 닫히는 소리",
            generation_prompt="A wooden door closes once in a quiet room, dry studio recording",
            duration_seconds=2.0,
            duration_mode="auto",
            translated=True,
            planner="local-llm",
        ),
    )

    response = client.post(
        "/api/sound-effects/generate",
        json={
            "prompt": "조용한 방에서 나무 문이 한 번 닫히는 소리",
            "auto_duration": True,
            "variations": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert adapter.calls[0]["prompt"] == "A wooden door closes once in a quiet room, dry studio recording"
    assert adapter.calls[0]["duration_seconds"] == 2.0
    assert payload["results"][0]["prompt"] == "조용한 방에서 나무 문이 한 번 닫히는 소리"
    assert payload["results"][0]["generation_prompt"].startswith("A wooden door")
    assert payload["plan"]["translated"] is True


def test_stt_endpoint_stores_uploaded_audio_and_returns_segments(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)

    def fake_transcribe(path: Path, offset_seconds: float = 0, **kwargs):
        return TranscriptSegmentsResponse(
            segments=[TranscriptSegment(start=offset_seconds, end=offset_seconds + 0.5, text="전사 결과")],
            text="전사 결과",
        )

    monkeypatch.setattr(main_module, "transcribe_with_segments", fake_transcribe)

    response = client.post(
        "/api/stt",
        data={"language": "ko"},
        files={"audio": ("sample.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "전사 결과"
    assert payload["segments"][0]["text"] == "전사 결과"
    assert payload["model"] == "base"


def test_recorded_speech_is_transcribed_before_generation(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post(
        "/api/speech-to-speech",
        data={"voice_id": "", "language": "ko"},
        files={"audio": ("speech.webm", b"recorded speech", "audio/webm")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript"] == "Transcribed speech placeholder"
    assert payload["audio_url"].startswith("/api/files/outputs/")


def test_blank_voice_name_gets_default_name_and_wav_reference(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post(
        "/api/voices",
        data={"name": "   ", "transcript": ""},
        files={"audio": ("browser-recording.webm", sample_wav_bytes(), "audio/webm")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"].startswith("샘플 목소리")
    assert payload["audio_url"].endswith(".wav")
    assert (tmp_path / "voices" / Path(payload["audio_url"]).name).exists()


def test_generate_accepts_audio_control_options(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine)

    response = client.post(
        "/api/generate",
        json={
            "text": "속도와 피치를 조절합니다.",
            "speed": 1.2,
            "quality": "fast",
            "pitch_shift": 1.0,
            "volume_gain_db": 2.0,
            "normalize_output": True,
            "duration": 8.0,
            "guidance_scale": 2.5,
            "denoise": False,
            "position_temperature": 1.0,
            "class_temperature": 0.2,
            "audio_chunk_duration": 12.0,
            "audio_chunk_threshold": 24.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audio_url"].startswith("/api/files/outputs/")
    assert (tmp_path / "outputs" / Path(payload["audio_url"]).name).exists()
    assert engine.last_kwargs["duration"] == 8.0
    assert engine.last_kwargs["guidance_scale"] == 2.5
    assert engine.last_kwargs["denoise"] is False
    assert engine.last_kwargs["position_temperature"] == 1.0
    assert engine.last_kwargs["class_temperature"] == 0.2
    assert engine.last_kwargs["audio_chunk_duration"] == 12.0
    assert engine.last_kwargs["audio_chunk_threshold"] == 24.0


def test_voice_conversion_returns_clear_not_configured_message(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Target", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/voice-conversion",
        data={"voice_id": voice["id"]},
        files={"audio": ("source.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 409
    assert "soulx-singer" in response.json()["detail"].lower()


def test_realtime_voice_conversion_endpoints_are_not_exposed(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    assert client.get("/api/voice-conversion/realtime/status").status_code == 404
    assert client.post("/api/voice-conversion/realtime/launch").status_code == 404


def test_voice_conversion_normalization_error_completes_progress(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    progress_id = "vc-normalize-error"

    def fail_normalize(*args, **kwargs):
        raise RuntimeError("선택 구간에서 변환할 음성을 찾지 못했습니다.")

    monkeypatch.setattr(voice_conversion_routes, "normalize_music_cover_audio", fail_normalize)
    progress_events.pop(progress_id, None)

    response = client.post(
        "/api/voice-conversion",
        data={"progress_id": progress_id},
        files={"audio": ("source.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 422
    assert "선택 구간" in response.json()["detail"]
    assert progress_events[progress_id]["done"] is True
    assert progress_events[progress_id]["percent"] == 100


def test_voice_conversion_passes_soulx_cover_options(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    adapter = AvailableVoiceConversionAdapter(tmp_path / "outputs")
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    voice = client.post(
        "/api/voices",
        data={"name": "Target", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/voice-conversion",
        data={
            "voice_id": voice["id"],
            "conversion_mode": "singing",
            "steps": "8",
            "cfg_scale": "2.4",
            "auto_shift": "false",
            "pitch_shift": "2",
            "separate_vocals": "true",
            "mix_accompaniment": "true",
            "seed": "123",
        },
        files={"audio": ("source.wav", sample_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversion_mode"] == "singing"
    assert payload["transcript"] == "captured transcript"
    assert adapter.calls[0]["conversion_mode"] == "singing"
    assert adapter.calls[0]["steps"] == 8
    assert adapter.calls[0]["cfg_scale"] == 2.4
    assert adapter.calls[0]["auto_shift"] is False
    assert adapter.calls[0]["pitch_shift"] == 2
    assert adapter.calls[0]["separate_vocals"] is True
    assert adapter.calls[0]["mix_accompaniment"] is True
    assert adapter.calls[0]["seed"] == 123


def test_generate_does_not_inject_default_reference_text_when_saved_voice_lacks_transcript(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    voice = client.post(
        "/api/voices",
        data={"name": "Legacy sample", "transcript": ""},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/generate",
        json={"text": "기존 목소리로 읽어 주세요.", "voice_id": voice["id"]},
    )

    assert response.status_code == 200
    assert engine.last_voice is not None
    assert engine.last_voice.transcript is None


def test_generate_does_not_forward_reference_transcript_as_script_text(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    voice = client.post(
        "/api/voices",
        data={"name": "Sample voice", "transcript": "이 문장은 실제 참조 음성의 대본입니다."},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/generate",
        json={"text": "이 문장만 음성으로 만들어 주세요.", "voice_id": voice["id"]},
    )

    assert response.status_code == 200
    assert engine.last_kwargs is not None
    assert engine.last_kwargs["text"] == "이 문장만 음성으로 만들어 주세요."
    assert engine.last_voice is not None
    assert engine.last_voice.transcript == "이 문장은 실제 참조 음성의 대본입니다."


def test_generate_strips_default_reference_prompt_from_saved_voice(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    voice = client.post(
        "/api/voices",
        data={
            "name": "Default prompt voice",
            "transcript": "안녕하세요. 이 목소리는 로컬 음성 합성을 위한 샘플입니다. 또렷하고 자연스럽게 말하며 억양과 발음이 잘 드러나도록 녹음합니다.",
        },
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/generate",
        json={"text": "실제 대본만 음성으로 만들어 주세요.", "voice_id": voice["id"]},
    )

    assert response.status_code == 200
    assert engine.last_voice is not None
    assert engine.last_voice.transcript is None


def test_generate_rejects_empty_audio_result(tmp_path: Path):
    client = client_with_mock_engine(tmp_path, engine=EmptyVoiceEngine(output_dir=tmp_path / "outputs"))

    response = client.post("/api/generate", json={"text": "오디오가 비어 있으면 실패해야 합니다."})

    assert response.status_code == 503
    assert "empty audio" in response.json()["detail"]


def test_generate_rejects_empty_text(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    response = client.post("/api/generate", json={"text": "   "})

    assert response.status_code == 422


def test_voice_upload_can_save_selected_time_range(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    buffer = BytesIO()
    sample_rate = 24000
    t = np.linspace(0, 20, 20 * sample_rate, endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(buffer, waveform, sample_rate, format="WAV")

    response = client.post(
        "/api/voices",
        data={"name": "Selected range", "transcript": "", "trim_start": "2", "trim_end": "12"},
        files={"audio": ("long.wav", buffer.getvalue(), "audio/wav")},
    )

    assert response.status_code == 201
    payload = response.json()
    info = sf.info(tmp_path / "voices" / Path(payload["audio_url"]).name)
    assert 9.9 <= info.duration <= 10.1


def test_voice_can_be_deleted(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Delete me", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.delete(f"/api/voices/{voice['id']}")

    assert response.status_code == 204
    assert client.get("/api/voices").json() == []


def test_voice_info_and_selected_range_can_be_updated(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    buffer = BytesIO()
    sample_rate = 24000
    t = np.linspace(0, 20, 20 * sample_rate, endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(buffer, waveform, sample_rate, format="WAV")
    voice = client.post(
        "/api/voices",
        data={"name": "Before", "transcript": "old", "trim_start": "0", "trim_end": "15"},
        files={"audio": ("long.wav", buffer.getvalue(), "audio/wav")},
    ).json()

    response = client.patch(
        f"/api/voices/{voice['id']}",
        json={"name": "After", "transcript": "new transcript", "trim_start": 3, "trim_end": 13},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "After"
    assert payload["transcript"] == "new transcript"
    assert payload["trim_start"] == 3
    assert payload["trim_end"] == 13
    info = sf.info(tmp_path / "voices" / Path(payload["audio_url"]).name)
    assert 9.9 <= info.duration <= 10.1


def test_settings_smoke_endpoints_report_voice_and_translation_status(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    voice_response = client.post("/api/settings/test-voice", json={"text": "테스트 음성입니다."})
    translation_response = client.post("/api/settings/test-translation", json={"text": "안녕하세요", "languages": ["en"]})

    assert voice_response.status_code == 200
    assert voice_response.json()["audio_url"].startswith("/api/files/outputs/")
    assert translation_response.status_code in {200, 503}
    assert "ok" in translation_response.json()


def test_korean_tone_prompt_is_mapped_to_supported_omnivoice_instruct():
    assert normalize_omnivoice_instruct("화난 톤으로") == "high pitch"
    assert normalize_omnivoice_instruct("슬픈 톤") == "low pitch"
    assert normalize_omnivoice_instruct("차분하게") == "low pitch"
    assert normalize_omnivoice_instruct("차분하고 부드러운 여성 목소리") == "female, low pitch"
    assert normalize_omnivoice_instruct("밝고 신나는 어린아이 톤") == "child, high pitch"
    assert normalize_omnivoice_instruct("속삭이듯 낮은 톤") == "whisper, low pitch"


def test_unsupported_omnivoice_instruct_is_not_forwarded():
    assert normalize_omnivoice_instruct("화난 톤으로") != "화난 톤으로"
    assert normalize_omnivoice_instruct("감정적으로 아주 세게") is None


def test_language_target_adds_native_pronunciation_instruct_when_supported():
    assert language_code_to_omnivoice_language("en") == "English"
    assert language_code_to_omnivoice_language("ja") == "Japanese"
    assert language_code_to_omnivoice_language("fr") == "French"
    assert combine_omnivoice_instruct("차분하게", "en") == "low pitch, american accent"
    assert combine_omnivoice_instruct("차분하게", "ja") == "low pitch, japanese accent"
    assert combine_omnivoice_instruct("차분하게", "fr") == "low pitch"
    assert combine_omnivoice_instruct("차분하게", "en", "british accent") == "low pitch, british accent"
    assert combine_omnivoice_instruct("차분하게", "ja", "british accent") == "low pitch, japanese accent"


def test_generation_preview_shows_effective_language_accent_and_instruct(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()

    response = client.post(
        "/api/generation/preview",
        json={"voice_id": voice["id"], "language": "en", "tone_prompt": "차분하게", "accent": "british accent", "speed": 1.1, "duration": 12},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "clone"
    assert payload["voice_name"] == "Narrator"
    assert payload["language_hint"] == "English"
    assert payload["accent_hint"] == "british accent"
    assert payload["effective_instruct"] == "low pitch, british accent"
    assert "영어는 선택한 british accent 억양 힌트를 적용합니다." in payload["notes"]


def test_generation_preview_uses_native_accent_for_translated_languages(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)

    japanese = client.post(
        "/api/generation/preview",
        json={"voice_id": None, "language": "ja", "tone_prompt": "밝게", "accent": "british accent"},
    ).json()
    french = client.post(
        "/api/generation/preview",
        json={"voice_id": None, "language": "fr", "tone_prompt": "밝게", "accent": "british accent"},
    ).json()

    assert japanese["mode"] == "design"
    assert japanese["language_hint"] == "Japanese"
    assert japanese["accent_hint"] == "japanese accent"
    assert japanese["effective_instruct"] == "high pitch, japanese accent"
    assert french["language_hint"] == "French"
    assert french["accent_hint"] is None
    assert french["effective_instruct"] == "high pitch"


def test_content_generation_allows_voice_design_without_registered_voice(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    content = client.post(
        "/api/contents",
        json={"title": "Voice design", "source_text": "자동 목소리로 읽어 주세요.", "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": None, "languages": ["ko"], "tone_prompt": "female, low pitch", "num_step": 16},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["voice_id"] is None
    assert payload["results"][0]["voice_name"] == "Voice Design"
    assert engine.last_kwargs is not None
    assert engine.last_kwargs["voice"] is None
    assert engine.last_kwargs["instruct"] == "female, low pitch, korean accent"


def test_content_generation_missing_content_completes_progress(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    progress_id = "missing-content"
    progress_events.pop(progress_id, None)

    response = client.post(
        "/api/contents/not-found/generate",
        json={"progress_id": progress_id, "voice_id": None, "languages": ["ko"]},
    )

    assert response.status_code == 404
    assert progress_events[progress_id]["done"] is True
    assert progress_events[progress_id]["percent"] == 100


def test_content_generation_missing_voice_completes_progress(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    content = client.post(
        "/api/contents",
        json={"title": "Missing voice", "source_text": "읽을 대본입니다.", "translations": {}},
    ).json()
    progress_id = "missing-voice"
    progress_events.pop(progress_id, None)

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"progress_id": progress_id, "voice_id": "missing", "languages": ["ko"]},
    )

    assert response.status_code == 404
    assert progress_events[progress_id]["done"] is True
    assert progress_events[progress_id]["percent"] == 100


def test_content_generation_empty_targets_completes_progress(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    content = client.post(
        "/api/contents",
        json={"title": "No translation", "source_text": "한국어만 있습니다.", "translations": {}},
    ).json()
    progress_id = "empty-targets"
    progress_events.pop(progress_id, None)

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"progress_id": progress_id, "voice_id": None, "languages": ["en"]},
    )

    assert response.status_code == 422
    assert progress_events[progress_id]["done"] is True
    assert progress_events[progress_id]["percent"] == 100



def test_content_generation_passes_supported_tone_instruct_to_voice_engine(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()
    content = client.post(
        "/api/contents",
        json={"title": "Tone script", "source_text": "화난 톤 테스트입니다.", "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": voice["id"], "languages": ["ko"], "tone_prompt": "화난 톤으로", "speed": 1.0, "num_step": 16},
    )

    assert response.status_code == 200
    assert engine.last_kwargs is not None
    assert engine.last_kwargs["voice"].transcript == "Reference text"
    assert engine.last_kwargs["language"] == "Korean"
    assert engine.last_kwargs["instruct"] == "high pitch, korean accent"
    assert engine.last_kwargs["duration"] < 10


def test_content_generation_passes_translation_language_to_voice_engine(tmp_path: Path):
    engine = CapturingVoiceEngine(output_dir=tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path, engine=engine)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()
    content = client.post(
        "/api/contents",
        json={"title": "English script", "source_text": "안녕하세요.", "translations": {"en": "Hello. This is a native English pronunciation test."}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": voice["id"], "languages": ["en"], "tone_prompt": "차분하게", "accent": "british accent", "speed": 1.0, "num_step": 16},
    )

    assert response.status_code == 200
    assert engine.last_kwargs is not None
    assert engine.last_kwargs["language"] == "English"
    assert engine.last_kwargs["instruct"] == "low pitch, british accent"
    assert response.json()["results"][0]["effective_instruct"] == "low pitch, british accent"
    assert response.json()["results"][0]["language_hint"] == "English"


def test_content_generation_with_voxcpm_keeps_script_text_separate_from_prompts(tmp_path: Path):
    adapter = AvailableVoxCPMAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    script = "대본에 적힌 이 문장만 음성으로 만들어야 합니다."
    content = client.post(
        "/api/contents",
        json={"title": "VoxCPM prompt separation", "source_text": script, "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={
            "model_id": "voxcpm",
            "voice_id": None,
            "languages": ["ko"],
            "tone_prompt": "차분하게",
            "style_prompt": "모델에 추가로 전달할 스타일 지시",
            "speed": 1.2,
            "num_step": 16,
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert adapter.calls[0]["text"] == script
    assert "차분하게" not in adapter.calls[0]["text"]
    assert "스타일 지시" not in adapter.calls[0]["text"]
    assert "calm and steady tone" in adapter.calls[0]["instruct"]
    assert "모델에 추가로 전달할 스타일 지시" in adapter.calls[0]["instruct"]
    assert payload["results"][0]["text"] == script
    assert payload["results"][0]["model_id"] == "voxcpm"


def test_content_generation_with_voxcpm_auto_chunks_long_translation(tmp_path: Path):
    adapter = AvailableVoxCPMAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    progress_id = "voxcpm-long-ja"
    progress_events.pop(progress_id, None)
    long_japanese = (
        "ようこそ、コーディジョンチャンネルでは、主にカント哲学を中心に、様々な哲学者の思想を紹介します。"
        "難しい概念もできるだけ平易な言葉で説明し、初めて聞く方にも自然に届くようにお話しします。"
        "知識と書籍の前では、誰もが平等であり、学びはいつでも始められます。"
        "今日はその考えを、落ち着いた声でゆっくり共有します。"
    )
    content = client.post(
        "/api/contents",
        json={"title": "Japanese long script", "source_text": "원문", "translations": {"ja": long_japanese}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={
            "progress_id": progress_id,
            "model_id": "voxcpm",
            "languages": ["ja"],
            "tone_prompt": "차분하게",
            "style_prompt": "모델에만 전달할 스타일 지시",
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["text"] == long_japanese
    assert payload["results"][0]["model_id"] == "voxcpm"
    assert len(adapter.calls) > 1
    assert "".join(call["text"].replace(" ", "") for call in adapter.calls) == long_japanese.replace(" ", "")
    assert all("스타일 지시" not in call["text"] for call in adapter.calls)
    assert "calm and steady tone" in adapter.calls[0]["instruct"]
    assert progress_events[progress_id]["done"] is True


def test_content_generation_with_voxcpm_keeps_moderate_korean_script_single_pass(tmp_path: Path):
    adapter = AvailableVoxCPMAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    korean_script = (
        "추억을 그냥 간직하는 게 아니라, 다시 재생하는 법. "
        "이 남자는 기록되지 않은 기억은 사라지기 마련이라고 말합니다. "
        "누군가에게 고마움을 전하고 싶을 때, 혹은 아이의 소중한 순간을 영원히 복제하고 싶을 때, "
        "그는 종이 한 장에 디지털 감성을 통째로 집어넣습니다. "
        "상장을 주는 남자, 상주님. 평범한 일상을 영화 같은 순간으로 바꿔주는 이 남자의 정체를 지금 바로 확인해 보시죠. "
        "당신은 오늘, 누구에게 상을 주고 싶으신가요?"
    )
    content = client.post(
        "/api/contents",
        json={"title": "Korean medium script", "source_text": korean_script, "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={
            "model_id": "voxcpm",
            "languages": ["ko"],
            "tone_prompt": "차분하게",
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["text"] == korean_script
    assert response.json()["results"][0]["text"] == korean_script


def test_content_generation_with_voxcpm_auto_chunks_long_korean_duration_even_with_duration_hint(tmp_path: Path):
    adapter = AvailableVoxCPMAdapter(tmp_path / "outputs")
    client = client_with_mock_engine(tmp_path)
    app.dependency_overrides[main_module.get_router] = lambda: SingleAdapterRouter(adapter)
    korean_script = (
        "여기 한 남자가 있습니다. "
        "오랫동안 코드를 만져온 베테랑, 머릿속엔 이미 완성된 앱의 설계도가 가득하죠. "
        "그가 만들려는 건 뜻밖에도 상장입니다. "
        "책을 사고 유튜브를 뒤져봐도, 이론은 구름 위를 떠다니고 예제는 내 상황과 맞지 않습니다. "
    ) * 8
    content = client.post(
        "/api/contents",
        json={"title": "Korean long duration script", "source_text": korean_script, "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={
            "model_id": "voxcpm",
            "languages": ["ko"],
            "tone_prompt": "흥미진진하게",
            "style_prompt": "유튜브홍보영상 스타일로",
            "speed": 0.8,
            "duration": 180,
            "normalize_output": False,
        },
    )

    assert response.status_code == 200
    assert len(adapter.calls) > 1
    assert "".join(call["text"].replace(" ", "") for call in adapter.calls) == korean_script.strip().replace(" ", "")
    assert all("유튜브홍보영상 스타일" not in call["text"] for call in adapter.calls)
    assert all("energetic promotional video narration" in call["instruct"] for call in adapter.calls)
    assert all("excited and engaging tone" in call["instruct"] for call in adapter.calls)
    assert len({call["instruct"] for call in adapter.calls}) == 1
    assert all(call["speed"] == 0.8 for call in adapter.calls)
    assert response.json()["results"][0]["text"] == korean_script.strip()


def test_content_can_store_translations_and_generate_outputs_sequentially(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()
    content = client.post(
        "/api/contents",
        json={
            "title": "Campaign script",
            "source_text": "안녕하세요. 오늘의 안내입니다.",
            "translations": {"en": "Hello. This is today's notice."},
        },
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": voice["id"], "languages": ["ko", "en"], "tone_prompt": "차분하게", "speed": 1.0, "num_step": 16},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == content["id"]
    assert {result["language"] for result in payload["results"]} == {"ko", "en"}
    assert all(result["audio_url"].startswith("/api/files/outputs/") for result in payload["results"])
    assert client.get("/api/contents").json()[0]["id"] == content["id"]


def test_generated_content_result_can_be_saved_as_voice_profile(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    content = client.post(
        "/api/contents",
        json={"title": "Design result", "source_text": "이 결과를 새 목소리로 저장합니다.", "translations": {}},
    ).json()
    generated = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": None, "languages": ["ko"], "tone_prompt": "female, low pitch", "num_step": 16},
    ).json()
    result = generated["results"][0]

    response = client.post(
        f"/api/contents/{content['id']}/results/{result['id']}/save-voice",
        json={"name": "Saved Design Voice"},
    )

    assert response.status_code == 201
    voice = response.json()
    assert voice["name"] == "Saved Design Voice"
    assert voice["transcript"] == result["text"]
    assert voice["audio_url"].startswith("/api/files/voices/")
    assert voice["source_audio_url"].startswith("/api/files/uploads/")
    assert (tmp_path / "voices" / Path(voice["audio_url"]).name).exists()
    assert (tmp_path / "uploads" / Path(voice["source_audio_url"]).name).exists()

    voices = client.get("/api/voices").json()
    assert any(item["id"] == voice["id"] for item in voices)


def test_generated_content_result_save_voice_requires_existing_result(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    content = client.post(
        "/api/contents",
        json={"title": "Empty result", "source_text": "아직 결과가 없습니다.", "translations": {}},
    ).json()

    response = client.post(
        f"/api/contents/{content['id']}/results/missing/save-voice",
        json={"name": "Missing"},
    )

    assert response.status_code == 404


def test_content_generation_keeps_language_history_and_deletes_single_result(tmp_path: Path):
    client = client_with_mock_engine(tmp_path)
    voice = client.post(
        "/api/voices",
        data={"name": "Narrator", "transcript": "Reference text"},
        files={"audio": ("voice.wav", sample_wav_bytes(), "audio/wav")},
    ).json()
    content = client.post(
        "/api/contents",
        json={"title": "History script", "source_text": "안녕하세요.", "translations": {"en": "Hello."}},
    ).json()

    first = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": voice["id"], "languages": ["en"], "tone_prompt": "차분하게", "num_step": 16},
    ).json()
    second_response = client.post(
        f"/api/contents/{content['id']}/generate",
        json={"voice_id": voice["id"], "languages": ["en"], "tone_prompt": "밝게", "num_step": 16},
    )

    assert second_response.status_code == 200
    second = second_response.json()
    english_results = [result for result in second["results"] if result["language"] == "en"]
    assert len(english_results) == 2
    assert english_results[0]["id"] != english_results[1]["id"]
    assert english_results[0]["tone_prompt"] == "밝게"
    assert any(result["id"] == first["results"][0]["id"] for result in english_results)

    deleted_audio_path = tmp_path / "outputs" / Path(english_results[0]["audio_url"]).name
    assert deleted_audio_path.exists()

    delete_response = client.delete(f"/api/contents/{content['id']}/results/{english_results[0]['id']}")
    assert delete_response.status_code == 200
    remaining = delete_response.json()["results"]
    assert len([result for result in remaining if result["language"] == "en"]) == 1
    assert all(result["id"] != english_results[0]["id"] for result in remaining)
    assert not deleted_audio_path.exists()


def test_media_info_endpoint_confirms_a_link_without_importing(tmp_path: Path, monkeypatch):
    from app.services.media_import_service import MediaInfo

    client = client_with_mock_engine(tmp_path)

    def fake_inspect(url: str, settings: Settings):
        return MediaInfo(
            platform="youtube", title="샘플 영상", webpage_url=url, duration_seconds=95.0, uploader="채널", max_duration_seconds=3600
        )

    monkeypatch.setattr(main_module, "inspect_media", fake_inspect)

    response = client.post("/api/audio/media-info", json={"url": "https://youtu.be/WuW8V7US-0o"})

    assert response.status_code == 200
    assert response.json() == {
        "platform": "youtube",
        "title": "샘플 영상",
        "webpage_url": "https://youtu.be/WuW8V7US-0o",
        "duration_seconds": 95.0,
        "uploader": "채널",
        "max_duration_seconds": 3600,
    }


def test_media_import_endpoint_forwards_the_clip_range_only_when_given(tmp_path: Path, monkeypatch):
    client = client_with_mock_engine(tmp_path)
    imported_audio = tmp_path / "uploads" / "clip.wav"
    imported_audio.parent.mkdir(parents=True, exist_ok=True)
    imported_audio.write_bytes(sample_wav_bytes())
    seen: list[dict] = []

    def fake_import(url: str, settings: Settings, isolate_voice: bool = False, **clip):
        seen.append(clip)
        return MediaAudioImport(platform="youtube", title="t", webpage_url=url, duration_seconds=5.0, audio_path=imported_audio)

    monkeypatch.setattr(main_module, "import_media_audio", fake_import)

    client.post("/api/audio/media-import", json={"url": "https://youtu.be/WuW8V7US-0o"})
    client.post("/api/audio/media-import", json={"url": "https://youtu.be/WuW8V7US-0o", "start_seconds": 10, "end_seconds": 20})

    assert seen == [{}, {"start_seconds": 10, "end_seconds": 20}]
