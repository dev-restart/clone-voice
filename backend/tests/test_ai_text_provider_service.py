import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.services.ai_text_provider_service import (
    AiTextCompletion,
    AiTextProviderService,
    AiTextSelection,
    AiTextSettingsStore,
    _parse_codex_message,
    _parse_kimi_message,
)


def test_ai_text_settings_store_persists_only_provider_and_model(tmp_path: Path):
    path = tmp_path / "private" / "ai_text_settings.json"
    store = AiTextSettingsStore(path, "translategemma:12b")

    store.save(AiTextSelection("chatgpt", "gpt-5.6-luna"))

    assert store.get() == AiTextSelection("chatgpt", "gpt-5.6-luna")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "provider_id": "chatgpt",
        "model_id": "gpt-5.6-luna",
    }
    assert path.stat().st_mode & 0o777 == 0o600


def test_parse_codex_message_returns_last_agent_message():
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "test"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "first"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final"}}),
        ]
    )

    assert _parse_codex_message(stdout) == "final"


def test_parse_kimi_message_supports_stream_content_blocks():
    stdout = json.dumps(
        {
            "role": "assistant",
            "content": [
                {"type": "think", "think": "hidden"},
                {"type": "text", "text": '{"ok":true}'},
            ],
        }
    )

    assert _parse_kimi_message(stdout) == '{"ok":true}'


def test_catalog_contains_local_and_subscription_providers(tmp_path: Path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path))
    monkeypatch.setattr(
        service,
        "_local_models",
        lambda: ([{"id": "translategemma:12b", "label": "translategemma:12b"}], True, "connected"),
    )
    monkeypatch.setattr(service, "_chatgpt_status", lambda: (True, "connected", "/usr/local/bin/codex"))
    monkeypatch.setattr(service, "_kimi_status", lambda: (True, "connected", "/usr/local/bin/kimi"))
    monkeypatch.setattr(service, "_kimi_models", lambda: [{"id": "k3", "label": "Kimi K3"}])

    catalog = service.catalog()

    assert [provider["id"] for provider in catalog["providers"]] == ["local", "chatgpt", "kimi", "apple"]
    assert catalog["providers"][1]["models"][0]["id"] == "gpt-5.6-luna"
    assert catalog["providers"][2]["models"][0]["id"] == "k3"


def test_complete_forwards_optional_max_tokens_to_local_provider(tmp_path: Path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path))
    monkeypatch.setattr(service.store, "get", lambda: AiTextSelection("local", "translategemma:12b"))
    captured: dict[str, int | None] = {}

    def fake_complete_local(prompt: str, system_prompt: str, model: str, *, max_tokens: int | None = None):
        captured["max_tokens"] = max_tokens
        return AiTextCompletion(content="{}", provider="local", model=model)

    monkeypatch.setattr(service, "_complete_local", fake_complete_local)

    result = service.complete("prompt", system_prompt="system", max_tokens=2048)

    assert result.provider == "local"
    assert captured["max_tokens"] == 2048


def test_complete_local_clamps_max_tokens_to_safe_limit(tmp_path: Path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path))
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service._complete_local("prompt", "system", "translategemma:12b", max_tokens=99999)

    assert result.content == "{}"
    assert captured["body"]["max_tokens"] == 4096
    assert urlparse(str(captured["url"])).path.endswith("/chat/completions")


def test_chatgpt_completion_keeps_developer_instructions_out_of_user_prompt(tmp_path: Path, monkeypatch):
    service = AiTextProviderService(Settings(storage_dir=tmp_path))
    captured: dict[str, object] = {}

    def fake_run(command, *, input, capture_output, text, timeout, env):
        captured["command"] = command
        captured["input"] = input
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("app.services.ai_text_provider_service._resolve_cli", lambda _: "/usr/local/bin/codex")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = service._complete_chatgpt("untrusted source text", "trusted dialogue rules", "gpt-5.6-luna")

    command = captured["command"]
    assert isinstance(command, list)
    assert "--config" in command
    assert f'developer_instructions={json.dumps("trusted dialogue rules")}' in command
    assert captured["input"] == "untrusted source text"
    assert result.content == '{"ok":true}'
