import json

import pytest

from app.config import Settings
from app.services.ai_text_provider_service import AiTextProviderService, AiTextSettingsStore


@pytest.mark.parametrize("payload", [[], None, "invalid", {"model_id": None}, {"provider_id": "local", "model_id": 42}])
def test_invalid_saved_ai_selection_recovers_to_local_defaults(tmp_path, payload):
    path = tmp_path / "ai_text_settings.json"
    path.write_text(json.dumps(payload))
    selection = AiTextSettingsStore(path, "qwen3:4b").get()
    assert selection.provider_id == "local"
    assert selection.model_id == "qwen3:4b"


@pytest.mark.parametrize("base_url", ["invalid-url", "http://[broken", "https://user:secret@localhost/v1"])
def test_invalid_local_connection_keeps_catalog_editable(tmp_path, monkeypatch, base_url):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    (tmp_path / "ai_text_connections.json").write_text(json.dumps({"local": {"base_url": base_url}}))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("Invalid connection must not send a request"))
    catalog = AiTextProviderService(settings).catalog()
    assert catalog["connections"]["local_only"] is True
    assert catalog["providers"][0]["available"] is False
    assert catalog["providers"][0]["message"]
    assert catalog["connections"]["local"]["base_url"] == ""
    assert "user:secret" not in json.dumps(catalog)


def test_malformed_compatible_url_does_not_crash_local_policy(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    (tmp_path / "ai_text_connections.json").write_text(json.dumps({"compatible": {"base_url": "http://[broken", "model_id": "test"}}))
    service = AiTextProviderService(settings)
    service.store.save(type(service.store.get())("compatible", "test"))
    monkeypatch.setattr(service, "_local_models", lambda: ([], False, "offline"))
    catalog = service.catalog()
    assert catalog["selection"]["provider_id"] == "local"
    assert catalog["api_providers"][0]["available"] is False


def test_undecodable_ai_settings_recover_with_local_policy(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    (tmp_path / "ai_text_settings.json").write_bytes(b"\xff\xfe")
    (tmp_path / "ai_text_connections.json").write_bytes(b"\xff\xfe")
    service = AiTextProviderService(settings)
    monkeypatch.setattr(service, "_local_models", lambda: ([], False, "offline"))
    catalog = service.catalog()
    assert catalog["selection"] == {"provider_id": "local", "model_id": "qwen3:4b"}
    assert catalog["connections"]["local_only"] is True


@pytest.mark.parametrize("kind", ["directory", "external_symlink"])
def test_public_download_rejects_nonfiles_and_external_symlinks(tmp_path, kind):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.files import router
    from app.config import get_settings

    settings = Settings(storage_dir=tmp_path, _env_file=None)
    settings.outputs_dir.mkdir()
    target = settings.outputs_dir / "fixture"
    if kind == "directory":
        target.mkdir()
    else:
        outside = tmp_path / "private.txt"
        outside.write_text("private fixture")
        target.symlink_to(outside)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        assert client.get("/api/files/outputs/fixture").status_code == 404


@pytest.mark.parametrize(("spoken_text", "explicit_transcript", "expected"), [
    ("에이피아이 안내입니다.", None, "에이피아이 안내입니다."),
    ("에이피아이 안내입니다.", "직접 확인한 대본", "직접 확인한 대본"),
    (None, None, "API 안내입니다."),
])
def test_generated_voice_reference_uses_the_recorded_spoken_script(tmp_path, monkeypatch, spoken_text, explicit_transcript, expected):
    from shutil import copyfile
    from app.api.routes import contents
    from app.schemas import ContentItem, ContentResult, ResultSaveVoiceRequest
    from app.services.content_store import ContentStore
    from app.services.voice_store import VoiceStore

    settings = Settings(storage_dir=tmp_path, _env_file=None)
    settings.outputs_dir.mkdir()
    (settings.outputs_dir / "take.wav").write_bytes(b"test audio normalization is covered separately")
    monkeypatch.setattr(contents, "normalize_reference_audio", lambda source, destination, **kwargs: copyfile(source, destination))
    result = ContentResult(language="ko", text="API 안내입니다.", spoken_text=spoken_text, audio_url="/api/files/outputs/take.wav")
    store = ContentStore(settings.contents_dir, settings)
    content = store.save(ContentItem(title="발음 교정 음성", source_text="API 안내입니다.", results=[result]))
    voice = contents.save_content_result_as_voice(
        content.id, result.id, ResultSaveVoiceRequest(transcript=explicit_transcript),
        settings, store, VoiceStore(settings.voices_dir, settings),
    )
    assert voice.transcript == expected
