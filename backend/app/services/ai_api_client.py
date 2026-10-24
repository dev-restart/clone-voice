"""Bounded, non-streaming text adapters for manually configured API connections."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from app.services.ai_api_profiles import ModelProfile, ProfileInput, request_url
from app.services.ai_text_connections import is_loopback_url


class ApiCallError(RuntimeError):
    def __init__(self, message: str, code: str = "upstream_error"):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiCallError("API가 다른 주소로 이동을 요청했습니다. 키 보호를 위해 차단했습니다. 기본 주소를 확인하세요.", "redirect_blocked")


_condition = threading.Condition()
_active: dict[str, int] = {}
_waiting: dict[str, int] = {}


@contextmanager
def connection_slot(key: str, limit: int, timeout: int):
    deadline = time.monotonic() + timeout
    with _condition:
        if _waiting.get(key, 0) >= 16:
            raise ApiCallError("이 연결의 대기 요청이 많습니다. 진행 중인 작업을 기다려 주세요.", "queue_full")
        _waiting[key] = _waiting.get(key, 0) + 1
        try:
            while _active.get(key, 0) >= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ApiCallError("AI 연결의 실행 순서를 기다리다 시간이 초과되었습니다.", "queue_timeout")
                _condition.wait(remaining)
            _active[key] = _active.get(key, 0) + 1
        finally:
            _waiting[key] -= 1
            if not _waiting[key]:
                _waiting.pop(key)
    try:
        yield
    finally:
        with _condition:
            _active[key] -= 1
            if not _active[key]:
                _active.pop(key)
            _condition.notify_all()


def validate_call(profile: dict, local_only: bool) -> None:
    if not profile["enabled"]:
        raise ApiCallError("사용 중지한 AI 연결입니다. 설정에서 연결을 활성화하세요.", "disabled")
    if local_only and not is_loopback_url(profile["base_url"]):
        raise ApiCallError("로컬 전용 설정으로 외부 API 호출을 차단했습니다.", "local_only")


def headers_for(profile: dict, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if profile["protocol"] == "anthropic_messages":
        headers["anthropic-version"] = "2023-06-01"
    headers.update(ProfileInput.check_headers(profile.get("extra_headers", {})))
    auth = profile["auth_type"]
    if auth != "none":
        if not api_key or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
            raise ApiCallError("유효한 API 키를 등록하세요.", "missing_key")
        headers["Authorization" if auth == "bearer" else "x-api-key"] = f"Bearer {api_key}" if auth == "bearer" else api_key
    return headers


def _http_json(url: str, *, headers: dict, timeout: int, body: dict | None = None) -> dict:
    # localhost requests do not inherit an HTTP proxy or follow a redirected key.
    parsed = urlsplit(url)
    if parsed.hostname == "localhost":
        netloc = f"127.0.0.1:{parsed.port}" if parsed.port else "127.0.0.1"
        url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
    request = urllib.request.Request(url, headers=headers, method="GET" if body is None else "POST", data=None if body is None else json.dumps(body, ensure_ascii=False).encode())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ApiCallError("AI 응답이 허용 크기를 초과했습니다.", "response_too_large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ApiCallError("API의 JSON 응답 구조를 확인하세요.", "invalid_response")
            return payload
    except urllib.error.HTTPError as exc:
        messages = {401: "API 키 인증에 실패했습니다.", 403: "API 키 또는 모델 사용 권한이 없습니다.", 404: "API 주소 또는 모델을 찾지 못했습니다.", 429: "제공처의 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요."}
        message = messages.get(exc.code, "API 요청이 거절되었습니다. API 형식·모델·설정을 확인하세요.")
        # Never include upstream bodies, URLs, headers or exception reprs.
        raise ApiCallError(f"{message} (HTTP {exc.code})", f"http_{exc.code}") from None
    except (TimeoutError, urllib.error.URLError, OSError):
        raise ApiCallError("API 서버에 연결하지 못했거나 응답 시간이 초과되었습니다. 주소·서버 실행·네트워크를 확인하세요.", "connection_failed") from None
    except (ValueError, UnicodeError):
        raise ApiCallError("API에서 올바른 JSON을 받지 못했습니다. 주소와 API 형식을 확인하세요.", "invalid_json") from None


def parse_text(payload: dict, protocol: str) -> str:
    parts: list[str] = []
    try:
        if payload.get("error"):
            raise ApiCallError("제공처가 오류를 반환했습니다. 모델과 호출 구성을 확인하세요.")
        if protocol == "openai_chat":
            choice = payload["choices"][0]
            reason = choice.get("finish_reason")
            if reason == "length":
                raise ApiCallError("AI 응답이 출력 길이 제한으로 잘렸습니다. 입력을 줄이거나 모델의 최대 출력 길이를 높이세요.", "truncated")
            message = choice["message"]
            if reason in {"content_filter", "tool_calls", "function_call"} or message.get("refusal") or message.get("tool_calls"):
                raise ApiCallError("모델이 텍스트 대신 거절 또는 도구 요청을 반환했습니다. 결과를 적용하지 않았습니다.", "unsupported_output")
            content = message["content"]
            if isinstance(content, str):
                parts = [content]
            elif isinstance(content, list):
                parts = [item["text"] for item in content if item.get("type") == "text" and isinstance(item.get("text"), str)]
        elif protocol == "anthropic_messages":
            reason = payload.get("stop_reason")
            if reason == "max_tokens":
                raise ApiCallError("AI 응답이 출력 길이 제한으로 잘렸습니다. 결과를 적용하지 않았습니다.", "truncated")
            if reason not in {"end_turn", "stop_sequence"}:
                raise ApiCallError("완료된 텍스트 응답이 아닙니다. 도구 요청·일시정지·거절 결과를 적용하지 않았습니다.", "unsupported_output")
            blocks = payload["content"]
            if any(item.get("type") in {"tool_use", "server_tool_use", "refusal"} for item in blocks):
                raise ApiCallError("지원하지 않는 도구 요청 또는 거절 응답입니다.", "unsupported_output")
            parts = [item["text"] for item in blocks if item.get("type") == "text" and isinstance(item.get("text"), str)]
        else:
            if payload.get("status") != "completed":
                raise ApiCallError("Responses 요청이 완료되지 않았거나 출력이 잘렸습니다. 결과를 적용하지 않았습니다.", "incomplete")
            for item in payload.get("output", []):
                if item.get("type") == "reasoning":
                    continue
                if item.get("type") != "message" or item.get("role") != "assistant":
                    raise ApiCallError("Responses가 텍스트 이외의 작업을 반환했습니다.", "unsupported_output")
                for block in item.get("content", []):
                    if block.get("type") == "refusal":
                        raise ApiCallError("모델이 요청을 거절했습니다.", "refusal")
                    if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                        parts.append(block["text"])
        text = "\n".join(parts).strip()
        if not text:
            raise ApiCallError("모델의 텍스트 응답이 비어 있습니다. 모델 ID와 출력 설정을 확인하세요.", "empty_response")
        return text
    except (TypeError, KeyError, IndexError, AttributeError):
        raise ApiCallError("응답이 선택한 API 형식과 일치하지 않습니다.", "invalid_response") from None


class AiApiClient:
    def __init__(self, profile: dict, key: str, *, scope: str, local_only: bool, before_request: Callable[[], None] | None = None):
        self.profile = profile
        self.key = key
        self.scope = scope
        self.local_only = local_only
        self.before_request = before_request
        validate_call(profile, local_only)

    def models(self) -> dict:
        if self.before_request:
            self.before_request()
        payload = _http_json(request_url(self.profile, "models"), headers=headers_for(self.profile, self.key), timeout=min(15, self.profile["timeout_seconds"]))
        models = []
        seen = set()
        items = payload.get("data")
        if not isinstance(items, list):
            raise ApiCallError("모델 목록 형식을 확인하지 못했습니다. 모델 ID를 직접 입력하세요.", "no_models")
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 255 or model_id in seen or any(ord(c) < 32 for c in model_id):
                continue
            if self.key and self.key in model_id:
                continue
            seen.add(model_id)
            label = str(item.get("display_name") or item.get("name") or model_id)
            if self.key:
                label = label.replace(self.key, "[redacted]")
            models.append({"id": model_id, "label": label[:120]})
            if len(models) == 200:
                break
        if not models:
            raise ApiCallError("모델 목록을 받지 못했습니다. 모델 ID를 직접 입력해 응답 테스트를 할 수 있습니다.", "no_models")
        return {"models": models, "has_more": bool(payload.get("has_more")) or len(models) == 200, "message": "모델 목록 조회만 완료했습니다. 추론·JSON·도구 지원을 보장하지 않습니다."}

    def complete(self, prompt: str, system: str, model_id: str, *, max_tokens: int | None = None, schema: dict | None = None) -> str:
        validate_call(self.profile, self.local_only)
        raw_model = next((m for m in self.profile["models"] if m["id"] == model_id), None)
        if not raw_model:
            raise ApiCallError("이 연결에 등록한 모델을 선택하세요.", "unknown_model")
        model = ModelProfile.model_validate(raw_model)
        if schema:
            system += "\nReturn a complete JSON object matching this schema. Do not add commentary:\n" + json.dumps(schema, ensure_ascii=False)
        if len(system) + len(prompt) > model.max_input_chars:
            raise ApiCallError("모델에 설정한 입력 문자 예산을 초과했습니다. 입력을 나누거나 모델 설정을 확인하세요. 원문을 자동으로 자르지 않았습니다.", "input_budget")
        output_limit = min(model.max_output_tokens, max_tokens) if max_tokens is not None else model.max_output_tokens
        protocol = self.profile["protocol"]
        output_limit = max(16 if protocol == "openai_responses" else 1, output_limit)
        if protocol == "openai_chat":
            body = {"model": model_id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], model.token_parameter: output_limit, "stream": False}
            if schema and model.structured_output == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "voice_production", "strict": True, "schema": schema}}
        elif protocol == "anthropic_messages":
            body = {"model": model_id, "system": system, "messages": [{"role": "user", "content": prompt}], "max_tokens": output_limit, "stream": False}
        else:
            body = {"model": model_id, "instructions": system, "input": prompt, "max_output_tokens": output_limit, "stream": False, "store": False}
            if schema and model.structured_output == "json_schema":
                body["text"] = {"format": {"type": "json_schema", "name": "voice_production", "strict": True, "schema": schema}}
        if model.temperature is not None:
            body["temperature"] = model.temperature
        headers = headers_for(self.profile, self.key)
        with connection_slot(f"{self.scope}:{self.profile['id']}", self.profile["max_concurrency"], self.profile["timeout_seconds"]):
            # Policies may have changed while this request was waiting for its slot.
            if self.before_request:
                self.before_request()
            if self.profile.get("local_engine") == "ollama":
                parsed = urlsplit(self.profile["base_url"])
                metadata = _http_json(f"{parsed.scheme}://{parsed.netloc}/api/show", headers=headers, timeout=10, body={"model": model_id})
                if metadata.get("remote_model") or metadata.get("remote_host") or "cloud" in model_id.lower():
                    raise ApiCallError("로컬 Ollama 연결에서는 클라우드 모델을 사용할 수 없습니다.", "local_only")
            if self.before_request:
                self.before_request()
            payload = _http_json(request_url(self.profile), headers=headers, timeout=self.profile["timeout_seconds"], body=body)
        content = parse_text(payload, protocol)
        if self.key and self.key in content:
            # A misconfigured or hostile upstream may echo authentication headers.
            # Do not persist those bytes as a translation or a draft either.
            raise ApiCallError("API 인증 정보가 응답에 포함되어 결과를 차단했습니다. 제공처 구성을 확인하세요.", "credential_in_response")
        return content
