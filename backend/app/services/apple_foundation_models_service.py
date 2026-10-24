"""Bounded on-device Apple AI calls through a small native Swift helper."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from app.config import Settings

APPLE_MODEL_ID = "apple-on-device"
_MAX_INPUT_BYTES = 128 * 1024
_MAX_WORKER_BYTES = 512 * 1024
_PROTOCOL_PREFIX = "CLONE_VOICE_APPLE_FM:"
_BUILD_LOCK = threading.Lock()
_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MESSAGES = {
    "available": "이 Mac의 Apple Intelligence 모델을 사용합니다. 별도 AI 서버나 API 키가 필요하지 않습니다.",
    "unsupported_platform": "Mac 기본 AI는 Apple Silicon Mac의 macOS 26 이상에서 사용할 수 있습니다.",
    "unsupported_architecture": "Mac 기본 AI를 사용하려면 Apple Silicon Mac과 arm64 Python이 필요합니다.",
    "unsupported_macos": "Mac 기본 AI를 사용하려면 macOS 26 이상으로 업데이트해 주세요.",
    "compiler_unavailable": "Mac 기본 AI 실행파일을 준비하려면 Apple Command Line Tools가 필요합니다. 터미널에서 xcode-select --install로 설치해 주세요.",
    "build_failed": "Mac 기본 AI 실행파일을 준비하지 못했습니다. macOS와 Command Line Tools 버전 및 저장 폴더 권한을 확인해 주세요.",
    "helper_missing": "Mac 기본 AI 실행 소스가 없습니다. Clone Voice 설치 파일을 확인해 주세요.",
    "apple_intelligence_not_enabled": "시스템 설정 > Apple Intelligence 및 Siri에서 Apple Intelligence를 켜 주세요.",
    "device_not_eligible": "이 Mac 또는 현재 실행 환경에서는 Apple Intelligence 모델을 사용할 수 없습니다.",
    "model_not_ready": "Apple Intelligence 모델 준비가 끝나지 않았습니다. 시스템 설정에서 모델 다운로드를 마친 뒤 다시 시도해 주세요.",
    "model_unavailable": "Apple Intelligence 모델 상태를 확인하지 못했습니다. 시스템 설정과 Apple AI 실행 환경을 확인해 주세요.",
    "context_window_exceeded": "Mac 기본 AI의 입력·출력 길이 한도를 초과했습니다. 본문을 짧게 나누어 다시 시도해 주세요.",
    "unsupported_language": "Mac 기본 AI가 요청한 언어를 지원하지 않습니다. 다른 번역 모델을 직접 선택해 주세요.",
    "content_refused": "Mac 기본 AI가 이 내용의 처리를 거절했습니다. 본문을 확인하거나 다른 번역 모델을 직접 선택해 주세요.",
    "busy": "Mac 기본 AI가 다른 요청을 처리 중입니다. 잠시 후 다시 시도해 주세요.",
    "empty_response": "Mac 기본 AI가 빈 응답을 반환했습니다. 본문을 확인하고 다시 시도해 주세요.",
    "invalid_response": "Mac 기본 AI 응답을 확인하지 못했습니다. 다시 시도해 주세요.",
    "input_too_large": "Mac 기본 AI에 전달할 본문이 너무 깁니다. 내용을 나누어 다시 시도해 주세요.",
    "invalid_request": "Mac 기본 AI 요청 형식이 올바르지 않습니다.",
    "timeout": "Mac 기본 AI 응답 시간이 초과되어 실행을 중단했습니다. 본문을 짧게 나누어 다시 시도해 주세요.",
    "worker_failed": "Mac 기본 AI 실행이 중단됐습니다. Apple Intelligence 상태와 백엔드 실행 환경의 시스템 서비스 접근 권한을 확인해 주세요.",
    "generation_failed": "Mac 기본 AI가 응답을 생성하지 못했습니다. Apple Intelligence 상태와 실행 환경을 확인하고 다시 시도해 주세요.",
}


class AppleFoundationModelsError(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code if reason_code in _MESSAGES else "generation_failed"
        super().__init__(_MESSAGES[self.reason_code])


def _status(reason_code: str) -> dict[str, Any]:
    code = reason_code if reason_code in _MESSAGES else "model_unavailable"
    return {"available": code == "available", "message": _MESSAGES[code], "model_id": APPLE_MODEL_ID, "reason_code": code}


def _platform_problem() -> str | None:
    if platform.system() != "Darwin":
        return "unsupported_platform"
    if platform.machine().lower() not in {"arm64", "aarch64"}:
        return "unsupported_architecture"
    try:
        if int(platform.mac_ver()[0].split(".", 1)[0]) < 26:
            return "unsupported_macos"
    except (ValueError, IndexError):
        return "unsupported_macos"
    return None


def _request(prompt: str, system_prompt: str, max_tokens: int | None) -> dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(system_prompt, str):
        raise AppleFoundationModelsError("invalid_request")
    if len(prompt.encode("utf-8")) + len(system_prompt.encode("utf-8")) > _MAX_INPUT_BYTES:
        raise AppleFoundationModelsError("input_too_large")
    try:
        limit = 1024 if max_tokens is None else min(max(int(max_tokens), 1), 4096)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AppleFoundationModelsError("invalid_request") from exc
    return {"action": "complete", "prompt": prompt, "system_prompt": system_prompt, "max_tokens": limit}


class AppleFoundationModelsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _runtime_dir(self) -> Path:
        return self.settings.storage_dir.expanduser().resolve() / "bin" / "apple-foundation-models"

    def _environment(self) -> dict[str, str]:
        # Remote provider keys and endpoints are not inherited.
        allowed = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "__CF_USER_TEXT_ENCODING")
        env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
        temporary = self._runtime_dir() / "tmp"
        temporary.mkdir(parents=True, exist_ok=True, mode=0o700)
        env.update({"TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary)})
        return env

    def _helper_binary(self) -> Path:
        source = Path(__file__).resolve().parents[2] / "scripts" / "apple_foundation_models.swift"
        try:
            source_bytes = source.read_bytes()
        except OSError as exc:
            raise AppleFoundationModelsError("helper_missing") from exc
        digest = hashlib.sha256(source_bytes).hexdigest()[:20]
        root = self._runtime_dir()
        binary = root / f"apple_fm_{digest}"
        with _BUILD_LOCK:
            if binary.is_file() and os.access(binary, os.X_OK):
                return binary
            compiler = Path("/usr/bin/swiftc")
            if not compiler.is_file():
                raise AppleFoundationModelsError("compiler_unavailable")
            temporary_binary = root / f".{binary.name}-{uuid4().hex}"
            try:
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                cache = root / "module-cache"
                cache.mkdir(exist_ok=True, mode=0o700)
                result = subprocess.run(
                    [str(compiler), "-parse-as-library", "-target", "arm64-apple-macos26.0",
                     "-module-cache-path", str(cache), str(source), "-o", str(temporary_binary)],
                    capture_output=True, text=True, timeout=90, check=False, env=self._environment(),
                )
                if result.returncode != 0 or not temporary_binary.is_file():
                    raise AppleFoundationModelsError("build_failed")
                temporary_binary.chmod(0o700)
                temporary_binary.replace(binary)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AppleFoundationModelsError("build_failed") from exc
            finally:
                try:
                    temporary_binary.unlink(missing_ok=True)
                except OSError:
                    pass
            return binary

    def _timeout(self) -> float:
        value = getattr(self.settings, "apple_intelligence_timeout_seconds", self.settings.llm_timeout_seconds)
        return min(max(float(value), 1.0), 600.0)

    def _invoke_worker(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        binary = self._helper_binary()
        try:
            result = subprocess.run(
                [str(binary)], input=json.dumps(request, ensure_ascii=False), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
                env=self._environment(),
            )
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kills and waits for this worker on timeout.
            raise AppleFoundationModelsError("timeout") from exc
        except (OSError, ValueError) as exc:
            raise AppleFoundationModelsError("worker_failed") from exc
        if result.returncode != 0:
            raise AppleFoundationModelsError("worker_failed")
        if len(result.stdout.encode("utf-8")) > _MAX_WORKER_BYTES:
            raise AppleFoundationModelsError("invalid_response")
        # Native diagnostics can contain source text; never return them to clients.
        for line in reversed(result.stdout.splitlines()):
            if not line.startswith(_PROTOCOL_PREFIX):
                continue
            try:
                payload = json.loads(line[len(_PROTOCOL_PREFIX):])
            except json.JSONDecodeError as exc:
                raise AppleFoundationModelsError("invalid_response") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
                raise AppleFoundationModelsError("invalid_response")
            if not payload["ok"]:
                raise AppleFoundationModelsError(str(payload.get("reason_code", "generation_failed")))
            return payload
        raise AppleFoundationModelsError("invalid_response")

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        problem = _platform_problem()
        if problem:
            return _status(problem)
        key = str(self._runtime_dir())
        with _STATUS_LOCK:
            cached = _STATUS_CACHE.get(key)
            if not refresh and cached and time.monotonic() - cached[0] < 5.0:
                return dict(cached[1])
            try:
                payload = self._invoke_worker({"action": "status"}, min(self._timeout(), 10.0))
                available = payload.get("available")
                if not isinstance(available, bool):
                    raise AppleFoundationModelsError("invalid_response")
                result = _status("available" if available else str(payload.get("reason_code", "model_unavailable")))
                if not available and result["available"]:
                    result = _status("invalid_response")
            except AppleFoundationModelsError as exc:
                result = _status(exc.reason_code)
            except OSError:
                result = _status("worker_failed")
            _STATUS_CACHE[key] = (time.monotonic(), result)
            return dict(result)

    def complete(self, prompt: str, *, system_prompt: str, max_tokens: int | None = None) -> str:
        request = _request(prompt, system_prompt, max_tokens)
        problem = _platform_problem()
        if problem:
            raise AppleFoundationModelsError(problem)
        # Availability is rechecked natively for every completion, independently of the cache.
        payload = self._invoke_worker(request, self._timeout())
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AppleFoundationModelsError("empty_response")
        if len(content.encode("utf-8")) > _MAX_WORKER_BYTES:
            raise AppleFoundationModelsError("invalid_response")
        return content.strip()
