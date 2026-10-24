from __future__ import annotations

import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings, get_settings
from app.services.ai_api_client import AiApiClient, ApiCallError, validate_call
from app.services.ai_api_credentials import CredentialError
from app.services.ai_api_profiles import AiApiProfilesStore, ProfileConflict, ProfileInput, RoutingInput, is_api_profile
from app.services.ai_text_provider_service import AiTextProviderService


class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def safe(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # Pydantic normally includes the original input in validation errors.
                # API-key and arbitrary-header bodies must never be reflected.
                return JSONResponse(status_code=422, content={"detail": "AI 연결 입력이 올바르지 않습니다. 이름·주소·모델·키·고급 설정을 확인하세요."})
        return safe


def local_ui(request: Request):
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "이 컴퓨터의 크론보이스 화면에서 AI 연결을 관리하세요.")


router = APIRouter(route_class=SafeValidationRoute, dependencies=[Depends(local_ui)])


def api_error(exc: Exception):
    if isinstance(exc, KeyError):
        return HTTPException(404, "AI 연결을 찾을 수 없습니다.")
    if isinstance(exc, ProfileConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(422, "연결 설정이 올바르지 않습니다. 주소·이름 중복·모델·변경 확인을 확인하세요.")
    if isinstance(exc, (ApiCallError, CredentialError, RuntimeError)):
        return HTTPException(503, str(exc))
    return HTTPException(500, "AI 연결을 처리하지 못했습니다. 입력은 화면에 보존됩니다.")


@router.get("/api/ai/connections")
def list_connections(settings: Settings = Depends(get_settings)):
    try:
        return AiApiProfilesStore(settings).public()
    except RuntimeError as exc:
        raise api_error(exc) from None


@router.post("/api/ai/connections", status_code=201)
def create_connection(request: ProfileInput, settings: Settings = Depends(get_settings)):
    try:
        store = AiApiProfilesStore(settings)
        profile = store.save(request)
        return {"profile": profile, **store.public()}
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None


@router.put("/api/ai/connections/{profile_id}")
def update_connection(profile_id: str, request: ProfileInput, settings: Settings = Depends(get_settings)):
    try:
        store = AiApiProfilesStore(settings)
        profile = store.save(request, profile_id)
        return {"profile": profile, **store.public()}
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None


@router.delete("/api/ai/connections/{profile_id}")
def delete_connection(profile_id: str, expected_revision: int = Query(ge=1), settings: Settings = Depends(get_settings)):
    try:
        return AiApiProfilesStore(settings).delete(profile_id, expected_revision)
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    model_id: str = Field(default="", max_length=255)


def probe_client(profile_id: str, request: ProbeRequest, settings: Settings):
    store = AiApiProfilesStore(settings)
    profile = store.find(profile_id)
    if profile["revision"] != request.expected_revision:
        raise ProfileConflict("연결이 변경되었습니다. 최신 설정을 다시 불러온 뒤 테스트하세요.")
    local_only = store.legacy.get()["local_only"]
    validate_call(profile, local_only)
    def guard():
        current_policy = store.legacy.get()["local_only"]
        validate_call(store.find(profile_id), current_policy)
        validate_call(profile, current_policy)
    return profile, AiApiClient(profile, store.key(profile), scope=str(store.path.absolute()), local_only=local_only, before_request=guard)


@router.post("/api/ai/connections/{profile_id}/models")
def discover_models(profile_id: str, request: ProbeRequest, settings: Settings = Depends(get_settings)):
    try:
        _, client = probe_client(profile_id, request, settings)
        return client.models()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None


@router.post("/api/ai/connections/{profile_id}/test")
def test_model(profile_id: str, request: ProbeRequest, settings: Settings = Depends(get_settings)):
    started = time.monotonic()
    try:
        profile, client = probe_client(profile_id, request, settings)
        model_id = request.model_id or profile["default_model_id"]
        content = client.complete("Reply with OK only.", "This is a connection test. Do not call tools.", model_id, max_tokens=256)
        if client.key:
            content = content.replace(client.key, "[API key redacted]")
        followed = content.strip().strip('"\'').rstrip(".!").upper() == "OK"
        return {"ok": True, "profile_id": profile_id, "revision": profile["revision"], "model_id": model_id, "elapsed_ms": round((time.monotonic() - started) * 1000), "content": content[:500], "instruction_followed": followed, "message": "모델의 텍스트 응답을 확인했습니다. 번역 품질·JSON·도구 지원 검증은 별도입니다."}
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None


@router.put("/api/ai/routing")
def update_task_routing(request: RoutingInput, settings: Settings = Depends(get_settings)):
    service = AiTextProviderService(settings)
    try:
        with AiApiProfilesStore._lock:
            builtin_catalog = None
            for route in (request.translation, request.writing, request.sound_prompt):
                if route is None:
                    continue
                if is_api_profile(route.provider_id):
                    service.validate_profile_selection(route.provider_id, route.model_id)
                else:
                    if builtin_catalog is None:
                        data = service.catalog()
                        builtin_catalog = data["providers"] + data["api_providers"]
                    provider = next((p for p in builtin_catalog if p["id"] == route.provider_id), None)
                    if not provider or not any(m["id"] == route.model_id for m in provider["models"]):
                        raise ValueError("등록된 연결과 모델을 선택하세요.")
                    if service.connections.get()["local_only"] and provider["connection_type"] != "local":
                        raise ApiCallError("로컬 전용 설정으로 외부 연결 선택을 차단했습니다.", "local_only")
            return service.api_profiles.save_routing(request)
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise api_error(exc) from None
