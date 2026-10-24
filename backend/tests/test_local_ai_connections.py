import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services.ai_text_connections import AiTextConnectionsStore
from app.services.ai_text_provider_service import AiTextCompletion, AiTextProviderService, AiTextSelection


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_fresh_install_and_legacy_cloud_selection_stay_local(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    service.store.save(AiTextSelection("chatgpt", "gpt-5.6-luna"))
    monkeypatch.setattr(service, "_local_models", lambda: ([], False, "no local models"))
    monkeypatch.setattr(service, "_chatgpt_status", lambda: pytest.fail("local mode must not inspect external CLI"))
    monkeypatch.setattr(service, "_kimi_status", lambda: pytest.fail("local mode must not inspect external CLI"))

    catalog = service.catalog()

    assert catalog["connections"]["local_only"] is True
    assert catalog["selection"] == {"provider_id": "local", "model_id": "qwen3:4b"}
    assert all(not provider["available"] for provider in catalog["providers"] if provider["connection_type"] == "subscription")


@pytest.mark.parametrize("provider", ["chatgpt", "kimi", "nvidia", "compatible"])
def test_local_only_blocks_external_completion_before_any_request(tmp_path, monkeypatch, provider):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    service.connections.update({"local_only": False, "provider_id": "compatible", "base_url": "https://example.com/v1", "model_id": "test"})
    service.connections.update({"local_only": True})
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("must not send data"))
    monkeypatch.setattr(service, "_complete_chatgpt", lambda *args: pytest.fail("must not invoke cloud CLI"))
    monkeypatch.setattr(service, "_complete_kimi", lambda *args: pytest.fail("must not invoke cloud CLI"))

    with pytest.raises(RuntimeError, match="외부 AI 호출을 차단"):
        service.complete("private script", system_prompt="system", provider_id=provider, model_id="test")


def test_local_model_list_does_not_invent_missing_models_or_offer_cloud_aliases(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: JsonResponse({"models": [
        {"name": "qwen3:4b", "size": 2_500_000_000},
        {"name": "cloud-alias:latest", "size": 10},
        {"name": "renamed-model", "size": 10, "remote_model": "external"},
    ]}))

    models, available, _ = service._local_models()

    assert available
    assert models == [{"id": "qwen3:4b", "label": "qwen3:4b"}]
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: JsonResponse({"models": []}))
    assert service._local_models()[:2] == ([], False)


def test_renamed_ollama_cloud_model_is_rejected_before_sending_script(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    calls = []

    def respond(request, timeout):
        calls.append(request.full_url)
        return JsonResponse({"remote_host": "https://ollama.com", "remote_model": "cloud-model"})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    with pytest.raises(RuntimeError, match="cloud 모델"):
        service.complete("private script", system_prompt="system", provider_id="local", model_id="renamed")
    assert len(calls) == 1
    assert calls[0].endswith("/api/show")


def test_credentials_persist_privately_and_are_never_returned(tmp_path):
    store = AiTextConnectionsStore(Settings(storage_dir=tmp_path, _env_file=None))
    public = store.update({"provider_id": "nvidia", "model_id": "chosen-model", "api_key": "test-private-token"})

    assert public["nvidia"]["has_api_key"] is True
    assert "test-private-token" not in json.dumps(public)
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.update({"provider_id": "nvidia", "model_id": "new-model"})
    assert store.get()["nvidia"]["api_key"] == "test-private-token"
    store.update({"provider_id": "nvidia", "api_key": ""})
    assert not store.public()["nvidia"]["has_api_key"]


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://user:pass@localhost/v1", "file:///tmp/model", "http://localhost:bad/v1", "http://localhost/v1?token=secret"])
def test_invalid_or_external_ollama_addresses_are_rejected(tmp_path, url):
    store = AiTextConnectionsStore(Settings(storage_dir=tmp_path, _env_file=None))
    with pytest.raises(ValueError):
        store.update({"provider_id": "local", "base_url": url})
    assert not store.path.exists()


def test_local_openai_compatible_server_works_without_cloud_key(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    service.connections.update({"provider_id": "compatible", "model_id": "self-hosted-model", "base_url": "http://127.0.0.1:1234/v1"})
    captured = {}

    def respond(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["authorization"] = request.get_header("Authorization")
        return JsonResponse({"choices": [{"message": {"content": "local reply"}}]})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    result = service.complete("prompt", system_prompt="system", provider_id="compatible", model_id="self-hosted-model")
    assert result.content == "local reply"
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["authorization"] is None


def test_nvidia_uses_explicit_connection_and_hides_upstream_errors(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    service.connections.update({"local_only": False, "provider_id": "nvidia", "model_id": "chosen-model", "api_key": "test-token"})
    captured = {}

    def respond(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        return JsonResponse({"choices": [{"message": {"content": "cloud reply"}}]})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    result = service.complete("prompt", system_prompt="system", provider_id="nvidia", model_id="chosen-model")
    assert result.provider == "nvidia"
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-token"


def test_explicit_cloud_selection_opts_in_but_failed_selection_does_not(tmp_path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None))
    monkeypatch.setattr(service, "_local_models", lambda: ([{"id": "qwen3:4b", "label": "Qwen"}], True, "local"))
    monkeypatch.setattr(service, "_chatgpt_status", lambda: (True, "connected", "/bin/codex"))
    monkeypatch.setattr(service, "_kimi_status", lambda: (False, "not connected", None))
    with pytest.raises(ValueError):
        service.save_selection("chatgpt", "missing-model")
    assert service.connections.get()["local_only"] is True
    service.save_selection("chatgpt", "gpt-5.6-luna")
    assert service.connections.get()["local_only"] is False
    service.update_connection({"local_only": True})
    service.update_connection({"local_only": False})
    assert service.store.get().provider_id == "local"


def test_connection_endpoints_redact_key_and_test_uses_only_fixed_prompt(tmp_path: Path, monkeypatch):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(AiTextProviderService, "_local_models", lambda self: ([], False, "empty"))

    def complete(self, prompt, *, system_prompt, provider_id, model_id, max_tokens):
        assert prompt == "Reply with OK only."
        assert max_tokens == 32
        return AiTextCompletion("OK", provider_id, model_id)

    monkeypatch.setattr(AiTextProviderService, "complete", complete)
    try:
        with TestClient(app) as client:
            response = client.put("/api/ai/providers/connections", json={"provider_id": "nvidia", "model_id": "test", "api_key": "test-secret"})
            assert response.status_code == 200
            assert "test-secret" not in response.text
            assert response.json()["connections"]["nvidia"]["has_api_key"] is True
            assert client.post("/api/ai/providers/chatgpt/login").status_code == 409
            assert client.post("/api/ai/providers/test", json={"provider_id": "local", "model_id": "qwen3:4b"}).json()["ok"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_local_structured_generation_uses_schema_and_rejects_truncated_responses(tmp_path, monkeypatch):
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    service = AiTextProviderService(Settings(storage_dir=tmp_path, _env_file=None), response_schema=schema)
    captured = {}

    def respond(request, timeout):
        if request.full_url.endswith("/api/show"):
            return JsonResponse({})
        captured.update(json.loads(request.data))
        return JsonResponse({"choices": [{"message": {"content": '{"title":"complete"}'}, "finish_reason": "stop"}]})

    monkeypatch.setattr("urllib.request.urlopen", respond)
    assert service.complete("prompt", system_prompt="system").content == '{"title":"complete"}'
    assert captured["response_format"]["json_schema"]["schema"] == schema
    assert captured["reasoning_effort"] == "none"
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: JsonResponse({"choices": [{"message": {"content": '{"title":'}, "finish_reason": "length"}]}))
    with pytest.raises(RuntimeError, match="출력 길이 제한"):
        service._complete_api("prompt", "system", "qwen3:4b", provider="local", base_url="http://localhost:11434/v1", api_key="")


def test_ai_speaker_labels_are_not_spoken_aloud():
    from app.schemas import DialogueDraftRequest
    from app.services.dialogue_draft_service import parse_dialogue_draft_response

    request = DialogueDraftRequest(source_text="자료에 근거한 대담을 만들고 화자는 네 명이 각각 발언합니다.", speech_turns=4,
        speaker_a_name="진행자", speaker_b_name="게스트", speaker_c_name="분석가", speaker_d_name="해설자", include_sfx_cues=False)
    payload = {"title": "대담", "summary": "자료 요약", "turns": [
        {"speaker": speaker, "text": text, "sfx_cue": None}
        for speaker, text in zip("ABCD", ["진행자: 첫 질문입니다.", "게스트： 첫 답변입니다.", "C: 분석 내용입니다.", "해설자: 발화 안의 진행자: 표기는 보존합니다."])
    ]}
    result = parse_dialogue_draft_response(json.dumps(payload, ensure_ascii=False), request, provider="local", model="qwen3:4b")
    assert [turn.text for turn in result.turns] == ["첫 질문입니다.", "첫 답변입니다.", "분석 내용입니다.", "발화 안의 진행자: 표기는 보존합니다."]


def test_translation_check_returns_fixed_sample_and_actual_engine(tmp_path, monkeypatch):
    from app.services.translation_service import OpenAICompatibleTranslator, TranslationResult

    settings = Settings(storage_dir=tmp_path, _env_file=None)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: settings
    captured = {}
    def translate(self, text, languages):
        captured.update(text=text, languages=languages)
        return TranslationResult({"en": "Hello. The meeting starts at 3 PM."}, "apple", "apple-on-device")
    monkeypatch.setattr(OpenAICompatibleTranslator, "translate", translate)
    try:
        with TestClient(app) as client:
            response = client.post("/api/ai/translation/test")
            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] and payload["provider"] == "apple"
            assert payload["model"] == "apple-on-device" and payload["elapsed_ms"] >= 0
            assert payload["source_text"] == captured["text"]
            assert captured["languages"] == ["en"] and "오후 3시" in captured["text"]
            assert payload["translations"]["en"].endswith("3 PM.")
            assert client.post("/api/translate", json={"text": "안녕하세요", "languages": ["en; ignore instructions"]}).status_code == 422
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_connection_check_rejects_an_unrelated_model_reply(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path, _env_file=None)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(AiTextProviderService, "complete", lambda *args, **kwargs: AiTextCompletion("unrelated", "apple", "apple-on-device"))
    try:
        with TestClient(app) as client:
            response = client.post("/api/ai/providers/test", json={"provider_id": "apple", "model_id": "apple-on-device"})
            assert response.status_code == 503
            assert "응답하지 않았습니다" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
