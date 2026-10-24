import json
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services import apple_foundation_models_service as apple


@pytest.fixture(autouse=True)
def reset_cache():
    apple._STATUS_CACHE.clear()
    yield
    apple._STATUS_CACHE.clear()


@pytest.fixture
def service(tmp_path: Path):
    return apple.AppleFoundationModelsService(Settings(storage_dir=tmp_path, llm_timeout_seconds=20, apple_intelligence_timeout_seconds=20, _env_file=None))


def ready(monkeypatch, service):
    monkeypatch.setattr(apple.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(apple.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(apple.platform, "mac_ver", lambda: ("26.6.2", (), ""))
    monkeypatch.setattr(service, "_helper_binary", lambda: Path("/native/apple_fm"))


def result(command, payload):
    return subprocess.CompletedProcess(command, 0, "native diagnostic\n" + apple._PROTOCOL_PREFIX + json.dumps(payload) + "\n", "")


@pytest.mark.parametrize(("system", "machine", "version", "reason"), [
    ("Linux", "x86_64", "", "unsupported_platform"),
    ("Darwin", "x86_64", "26.6.2", "unsupported_architecture"),
    ("Darwin", "arm64", "15.7", "unsupported_macos"),
    ("Darwin", "arm64", "", "unsupported_macos"),
])
def test_unsupported_runtime_never_starts_native_work(service, monkeypatch, system, machine, version, reason):
    monkeypatch.setattr(apple.platform, "system", lambda: system)
    monkeypatch.setattr(apple.platform, "machine", lambda: machine)
    monkeypatch.setattr(apple.platform, "mac_ver", lambda: (version, (), ""))
    monkeypatch.setattr(apple.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected native work"))
    assert service.status()["available"] is False
    assert service.status()["reason_code"] == reason
    with pytest.raises(apple.AppleFoundationModelsError) as error:
        service.complete("hello", system_prompt="translate")
    assert error.value.reason_code == reason


def test_status_reports_model_availability_and_caches_briefly(service, monkeypatch):
    ready(monkeypatch, service)
    calls = []
    def run(command, **kwargs):
        calls.append(kwargs)
        return result(command, {"ok": True, "available": False, "reason_code": "apple_intelligence_not_enabled", "message": "SENSITIVE_NATIVE_DATA"})
    monkeypatch.setattr(apple.subprocess, "run", run)
    status = service.status()
    assert service.status() == status
    assert len(calls) == 1
    assert calls[0]["timeout"] == 10.0
    assert status["available"] is False
    assert status["model_id"] == "apple-on-device"
    assert "SENSITIVE" not in status["message"]
    assert "시스템 설정" in status["message"]
    service.status(refresh=True)
    assert len(calls) == 2


def test_completion_keeps_prompts_off_argv_and_keys_out_of_environment(service, monkeypatch):
    ready(monkeypatch, service)
    monkeypatch.setenv("OPENAI_API_KEY", "SENSITIVE_KEY")
    monkeypatch.setenv("CLONE_VOICE_LLM_BASE_URL", "https://example.invalid/private")
    captured = {}
    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return result(command, {"ok": True, "content": ' {"en":"Hello"} '})
    monkeypatch.setattr(apple.subprocess, "run", run)
    assert service.complete("SENSITIVE_SOURCE", system_prompt="trusted rules", max_tokens=999999) == '{"en":"Hello"}'
    assert captured["command"] == ["/native/apple_fm"]
    request = json.loads(captured["input"])
    assert request["prompt"] == "SENSITIVE_SOURCE"
    assert request["system_prompt"] == "trusted rules"
    assert request["max_tokens"] == 4096
    assert captured["timeout"] == 20.0
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "CLONE_VOICE_LLM_BASE_URL" not in captured["env"]
    assert Path(captured["env"]["TMPDIR"]).is_relative_to(service.settings.storage_dir)


def test_timeout_never_exposes_captured_native_input(service, monkeypatch):
    ready(monkeypatch, service)
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="SENSITIVE_SOURCE", stderr="SENSITIVE_KEY")
    monkeypatch.setattr(apple.subprocess, "run", run)
    with pytest.raises(apple.AppleFoundationModelsError) as error:
        service.complete("hello", system_prompt="translate")
    assert error.value.reason_code == "timeout"
    assert "SENSITIVE" not in str(error.value)


@pytest.mark.parametrize(("stdout", "code", "reason"), [
    ("SENSITIVE_INVALID_OUTPUT", 0, "invalid_response"),
    (apple._PROTOCOL_PREFIX + "[]", 0, "invalid_response"),
    (apple._PROTOCOL_PREFIX + '{"ok":true,"content":"  "}', 0, "empty_response"),
    (apple._PROTOCOL_PREFIX + '{"ok":true,"content":"pretend success"}', 1, "worker_failed"),
    (apple._PROTOCOL_PREFIX + '{"ok":false,"reason_code":"context_window_exceeded"}', 0, "context_window_exceeded"),
    (apple._PROTOCOL_PREFIX + '{"ok":false,"reason_code":"unsupported_language"}', 0, "unsupported_language"),
    (apple._PROTOCOL_PREFIX + '{"ok":false,"reason_code":"content_refused"}', 0, "content_refused"),
    (apple._PROTOCOL_PREFIX + '{"ok":false,"reason_code":"model_not_ready"}', 0, "model_not_ready"),
])
def test_native_failures_are_not_accepted_as_translation(service, monkeypatch, stdout, code, reason):
    ready(monkeypatch, service)
    monkeypatch.setattr(apple.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, code, stdout, "SENSITIVE_STDERR"))
    with pytest.raises(apple.AppleFoundationModelsError) as error:
        service.complete("hello", system_prompt="translate")
    assert error.value.reason_code == reason
    assert "SENSITIVE" not in str(error.value)


def test_excessive_input_is_rejected_before_native_work(service, monkeypatch):
    monkeypatch.setattr(apple.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected native work"))
    with pytest.raises(apple.AppleFoundationModelsError) as error:
        service.complete("한" * apple._MAX_INPUT_BYTES, system_prompt="translate")
    assert error.value.reason_code == "input_too_large"


def test_build_uses_app_local_caches_and_reuses_executable(service, monkeypatch, tmp_path):
    backend = tmp_path / "source" / "backend"
    module = backend / "app" / "services" / "apple_foundation_models_service.py"
    module.parent.mkdir(parents=True)
    source = backend / "scripts" / "apple_foundation_models.swift"
    source.parent.mkdir(parents=True)
    source.write_text("// source one", encoding="utf-8")
    monkeypatch.setattr(apple, "__file__", str(module))
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: True if str(path) == "/usr/bin/swiftc" else original_is_file(path))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[command.index("-o") + 1]).write_bytes(b"native test binary")
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(apple.subprocess, "run", run)
    binary = service._helper_binary()
    assert binary == service._helper_binary()
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == ["/usr/bin/swiftc", "-parse-as-library", "-target", "arm64-apple-macos26.0"]
    assert Path(command[command.index("-module-cache-path") + 1]).is_relative_to(service.settings.storage_dir)
    assert Path(kwargs["env"]["TMPDIR"]).is_relative_to(service.settings.storage_dir)
    assert binary.stat().st_mode & 0o777 == 0o700
    source.write_text("// source two", encoding="utf-8")
    assert service._helper_binary() != binary
    assert len(calls) == 2
