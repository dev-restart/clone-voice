from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.config import Settings
from app.services.ai_api_credentials import ApiCredentialVault, CredentialError
from app.services.ai_text_connections import AiTextConnectionsStore, is_loopback_url, normalize_base_url

PROTOCOLS = ("openai_chat", "anthropic_messages", "openai_responses")
BUILTINS = ("apple", "local", "compatible", "nvidia", "chatgpt", "kimi")
TASKS = ("translation", "writing", "sound_prompt")
PROFILE_ID = re.compile(r"api-[a-z0-9-]{1,80}")


def is_api_profile(value: str) -> bool:
    return bool(PROFILE_ID.fullmatch(value))


def valid_provider(value: str) -> bool:
    return value in BUILTINS or is_api_profile(value)


def profile_url(value: str) -> str:
    if any(ord(char) < 33 or ord(char) == 127 for char in value.strip()):
        raise ValueError("API 주소에 공백이나 제어 문자를 사용할 수 없습니다.")
    url = normalize_base_url(value)
    for suffix in ("/chat/completions", "/messages", "/responses", "/models"):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
            break
    parsed = urlsplit(url)
    if parsed.scheme != "https" and not is_loopback_url(url):
        raise ValueError("외부 API에는 HTTPS 주소를 사용하세요. HTTP는 이 컴퓨터의 localhost에만 허용됩니다.")
    if any(part in {".", ".."} for part in parsed.path.split("/")) or "%" in parsed.netloc:
        raise ValueError("API 주소 경로를 확인하세요.")
    return url


def request_url(profile: dict, endpoint: str | None = None) -> str:
    path = endpoint or {"openai_chat": "chat/completions", "anthropic_messages": "messages", "openai_responses": "responses"}[profile["protocol"]]
    return f"{profile_url(profile['base_url'])}/{path}"


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=255)
    label: str = Field(default="", max_length=120)
    max_input_chars: int = Field(default=32000, ge=256, le=120000)
    max_output_tokens: int = Field(default=4096, ge=32, le=65536)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    structured_output: Literal["prompt", "json_schema"] = "prompt"

    @field_validator("id", "label")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("모델 정보에 제어 문자를 사용할 수 없습니다.")
        return value


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    protocol: Literal["openai_chat", "anthropic_messages", "openai_responses"] = "openai_chat"
    base_url: str = Field(min_length=1, max_length=2000)
    auth_type: Literal["none", "bearer", "x-api-key"] = "bearer"
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    credential_storage: Literal["keychain", "private_file"] = "keychain"
    confirm_destination_change: bool = False
    enabled: bool = True
    local_engine: Literal["generic", "ollama"] = "generic"
    models: list[ModelProfile] = Field(default_factory=list, max_length=30)
    default_model_id: str = Field(default="", max_length=255)
    timeout_seconds: int = Field(default=120, ge=5, le=600)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    extra_headers: dict[str, str] = Field(default_factory=dict, max_length=8)
    expected_revision: int = Field(default=0, ge=0)

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return profile_url(value)

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return ModelProfile.safe_text(value)

    @field_validator("api_key")
    @classmethod
    def check_key(cls, value: SecretStr | None):
        if value is not None:
            raw = value.get_secret_value()
            if not 1 <= len(raw) <= 4096 or any(ord(char) < 33 or ord(char) > 126 for char in raw):
                raise ValueError("API 키의 길이 또는 문자 형식이 올바르지 않습니다.")
        return value

    @field_validator("extra_headers")
    @classmethod
    def check_headers(cls, value: dict[str, str]):
        allowed = {"http-referer": "HTTP-Referer", "x-title": "X-Title", "anthropic-version": "anthropic-version", "anthropic-workspace-id": "anthropic-workspace-id", "openai-organization": "OpenAI-Organization", "openai-project": "OpenAI-Project"}
        result = {}
        for key, item in value.items():
            name = allowed.get(key.lower())
            if not name or name in result or not item or len(item) > 500 or any(ord(c) < 32 or ord(c) > 126 for c in item):
                raise ValueError("추가 헤더는 지원되는 이름과 한 줄 ASCII 값만 허용합니다. 인증 정보는 API 키 항목을 사용하세요.")
            result[name] = item
        return result

    @model_validator(mode="after")
    def consistent(self):
        ids = [model.id for model in self.models]
        if len(ids) != len(set(ids)) or (self.default_model_id and self.default_model_id not in ids):
            raise ValueError("모델 ID 중복 또는 기본 모델 설정을 확인하세요.")
        if not self.default_model_id and ids:
            self.default_model_id = ids[0]
        if self.local_engine == "ollama" and not is_loopback_url(self.base_url):
            raise ValueError("로컬 Ollama 연결에는 localhost 주소를 사용하세요.")
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("키 삭제와 새 키 입력 중 하나만 선택하세요.")
        if self.protocol == "anthropic_messages" and any(m.temperature is not None and m.temperature > 1 for m in self.models):
            raise ValueError("Anthropic Messages의 Temperature는 0~1 또는 서버 기본값을 사용하세요.")
        if self.protocol == "anthropic_messages" and any(m.structured_output == "json_schema" for m in self.models):
            raise ValueError("Anthropic 호환 연결은 JSON 프롬프트 모드를 사용하세요.")
        return self


class RouteSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider_id: str = Field(min_length=1, max_length=90)
    model_id: str = Field(min_length=1, max_length=255)

    @field_validator("provider_id")
    @classmethod
    def check_provider(cls, value: str):
        if not valid_provider(value):
            raise ValueError("지원하지 않는 AI 연결입니다.")
        return value


class RoutingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    translation: RouteSelection | None = None
    writing: RouteSelection | None = None
    sound_prompt: RouteSelection | None = None


class ProfileConflict(RuntimeError):
    pass


class AiApiProfilesStore:
    """One local backend process; atomic metadata + immutable credential references."""
    _lock = threading.RLock()

    def __init__(self, settings: Settings, vault: ApiCredentialVault | None = None):
        self.settings = settings
        self.path = settings.resolved_ai_text_settings_path.with_name("ai_api_profiles.json")
        self.vault = vault or ApiCredentialVault(self.path.parent / ".ai-api-secrets")
        self.legacy = AiTextConnectionsStore(settings)

    def _initial(self) -> dict:
        profiles = []
        for key, value in self.legacy.get().items():
            if key not in ("local", "compatible", "nvidia") or not isinstance(value, dict):
                continue
            if key != "local" and not (value.get("model_id") or value.get("api_key")):
                continue
            try:
                base = profile_url(value["base_url"])
            except ValueError:
                continue
            model = value.get("model_id", "")
            entry = ProfileInput(name={"local": "Ollama · 기존 연결", "compatible": "호환 API · 기존 연결", "nvidia": "NVIDIA · 기존 연결"}[key], base_url=base, auth_type="bearer" if value.get("api_key") else "none", local_engine="ollama" if key == "local" else "generic", models=[ModelProfile(id=model)] if model else [])
            profile = self._fields(entry)
            profile.update(id=f"api-legacy-{key}", revision=1, legacy_provider=key, credential_ref="", credential_storage="legacy", legacy_base_url=base, created_at="", updated_at="")
            profiles.append(profile)
        return {"version": 1, "revision": 0, "profiles": profiles, "routing": dict.fromkeys(TASKS)}

    @staticmethod
    def _fields(value: ProfileInput):
        return value.model_dump(mode="json", exclude={"api_key", "clear_api_key", "confirm_destination_change", "expected_revision"})

    def get(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return self._initial()
            try:
                if self.path.is_symlink() or self.path.stat().st_size > 2_000_000:
                    raise ValueError("invalid profiles file")
                result = json.loads(self.path.read_text(encoding="utf-8"))
                if result.get("version") != 1 or not isinstance(result.get("profiles"), list) or not isinstance(result.get("routing"), dict):
                    raise ValueError("invalid profiles format")
                return result
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise RuntimeError("AI 연결 설정을 읽지 못했습니다. 기존 파일을 덮어쓰지 않았습니다.") from exc

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        except OSError as exc:
            raise RuntimeError("AI 연결 저장에 실패했습니다. 입력 내용을 유지한 채 다시 시도하세요.") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def find(self, profile_id: str) -> dict:
        if not is_api_profile(profile_id):
            raise KeyError("AI 연결을 찾을 수 없습니다.")
        profile = next((p for p in self.get()["profiles"] if p["id"] == profile_id), None)
        if not profile:
            raise KeyError("삭제되었거나 존재하지 않는 AI 연결입니다.")
        return deepcopy(profile)

    def key(self, profile: dict) -> str:
        if profile["auth_type"] == "none":
            return ""
        if profile.get("credential_ref"):
            return self.vault.get(profile["credential_ref"], profile["credential_storage"])
        legacy_id = profile.get("legacy_provider")
        if profile.get("credential_storage") == "legacy" and legacy_id:
            values = self.legacy.get()[legacy_id]
            if profile_url(values["base_url"]) != profile["base_url"]:
                raise CredentialError("기존 연결 주소가 변경되어 키 사용을 중단했습니다. API 키를 다시 입력하세요.")
            return values.get("api_key", "")
        raise CredentialError("이 연결에 사용할 API 키를 입력하세요.")

    def public_profile(self, profile: dict) -> dict:
        has_key = bool(profile.get("credential_ref"))
        if profile.get("credential_storage") == "legacy" and profile.get("legacy_provider"):
            has_key = bool(self.legacy.get()[profile["legacy_provider"]].get("api_key"))
        public = {k: deepcopy(v) for k, v in profile.items() if k not in {"credential_ref", "retired_credentials", "legacy_provider", "legacy_base_url", "api_key"}}
        public["has_api_key"] = has_key
        public["request_url"] = request_url(profile)
        public["local"] = is_loopback_url(profile["base_url"])
        public["blocked"] = self.legacy.get()["local_only"] and not public["local"]
        public["status"] = "blocked" if public["blocked"] else "disabled" if not profile["enabled"] else "registered"
        return public

    def public(self) -> dict:
        data = self.get()
        return {"revision": data["revision"], "profiles": [self.public_profile(p) for p in data["profiles"]], "routing": data["routing"], "local_only": self.legacy.get()["local_only"], "credential_default": "keychain"}

    def save(self, request: ProfileInput, profile_id: str | None = None) -> dict:
        with self._lock:
            data = self.get()
            old = self.find(profile_id) if profile_id else None
            if old and old["revision"] != request.expected_revision:
                raise ProfileConflict("다른 화면에서 연결이 변경되었습니다. 입력을 보존하고 최신 설정을 다시 확인하세요.")
            if not old and len(data["profiles"]) >= 50:
                raise ValueError("AI 연결은 최대 50개까지 등록할 수 있습니다.")
            if any(p["id"] != profile_id and p["name"].casefold() == request.name.casefold() for p in data["profiles"]):
                raise ValueError("이미 사용 중인 연결 이름입니다. 다른 이름을 입력하세요.")
            profile_id = profile_id or f"api-{uuid4().hex}"
            profile = self._fields(request)
            key_changed = bool(request.api_key is not None or request.clear_api_key or request.auth_type == "none")
            if old:
                destination_changed = (old["base_url"], old["protocol"], old["auth_type"]) != (profile["base_url"], profile["protocol"], profile["auth_type"])
                if destination_changed and not request.confirm_destination_change:
                    raise ValueError("주소·API 형식·인증 방식 변경을 확인하세요. 저장된 키는 새 연결로 자동 전달되지 않습니다.")
                if destination_changed and not key_changed and self.public_profile(old)["has_api_key"]:
                    raise ValueError("연결 대상이 변경되었습니다. 사용할 키를 다시 입력하거나 기존 키 삭제를 선택하세요.")
                if request.credential_storage != old["credential_storage"] and old.get("credential_ref") and not key_changed:
                    raise ValueError("키 보관 방식을 변경하려면 API 키를 다시 입력하세요.")
                if not key_changed:
                    for name in ("credential_ref", "credential_storage", "legacy_provider", "legacy_base_url"):
                        if name in old:
                            profile[name] = old[name]
                removed = {m["id"] for m in old["models"]} - {m.id for m in request.models}
                active_routes = [v for v in data["routing"].values() if v and v["provider_id"] == profile_id and v["model_id"] in removed]
                try:
                    default = json.loads(self.settings.resolved_ai_text_settings_path.read_text())
                except (OSError, ValueError):
                    default = {}
                if active_routes or (default.get("provider_id") == profile_id and default.get("model_id") in removed):
                    raise ProfileConflict("기본 AI 또는 작업에서 사용하는 모델입니다. 사용할 모델을 먼저 변경하세요.")
            new_ref = ""
            if key_changed:
                profile["credential_ref"] = ""
            if request.api_key is not None and request.auth_type != "none":
                new_ref = self.vault.put(request.api_key.get_secret_value(), request.credential_storage)
                profile["credential_ref"] = new_ref
            retired = deepcopy(old.get("retired_credentials", [])) if old else []
            if old and key_changed and old.get("credential_ref"):
                retired.append({"reference": old["credential_ref"], "storage": old["credential_storage"]})
            profile["retired_credentials"] = retired
            now = datetime.now(timezone.utc).isoformat()
            profile.update(id=profile_id, revision=(old["revision"] if old else 0) + 1, created_at=old["created_at"] if old else now, updated_at=now)
            data["profiles"] = [profile if p["id"] == profile_id else p for p in data["profiles"]] if old else [*data["profiles"], profile]
            data["revision"] += 1
            try:
                self._write(data)
            except Exception:
                if new_ref:
                    self.vault.delete(new_ref, request.credential_storage)
                raise
            remaining = []
            for previous in retired:
                try:
                    self.vault.delete(previous["reference"], previous["storage"])
                except (CredentialError, OSError):
                    remaining.append(previous)
            if remaining != retired:
                profile["retired_credentials"] = remaining
                try:
                    self._write(data)
                except RuntimeError:
                    # The saved references allow idempotent cleanup on a later save.
                    remaining = retired
            result = self.public_profile(profile)
            if remaining:
                result["credential_warning"] = "연결은 저장했지만 이전 키 보관소 정리는 완료하지 못했습니다. 다음 저장 시 다시 정리합니다."
            return result

    def delete(self, profile_id: str, expected_revision: int) -> dict:
        with self._lock:
            data = self.get()
            profile = self.find(profile_id)
            if profile["revision"] != expected_revision:
                raise ProfileConflict("연결이 변경되었습니다. 최신 상태를 확인한 뒤 삭제하세요.")
            try:
                default = json.loads(self.settings.resolved_ai_text_settings_path.read_text())
            except (OSError, ValueError):
                default = {}
            if default.get("provider_id") == profile_id or any(v and v["provider_id"] == profile_id for v in data["routing"].values()):
                raise ProfileConflict("기본 AI 또는 작업에 지정된 연결입니다. 다른 연결로 변경한 뒤 삭제하세요.")
            data["profiles"] = [p for p in data["profiles"] if p["id"] != profile_id]
            data["revision"] += 1
            self._write(data)
            warning = None
            references = profile.get("retired_credentials", []) + ([{"reference": profile["credential_ref"], "storage": profile["credential_storage"]}] if profile.get("credential_ref") else [])
            for previous in references:
                try:
                    self.vault.delete(previous["reference"], previous["storage"])
                except (CredentialError, OSError):
                    warning = "연결은 삭제했지만 키 보관소 정리는 완료하지 못했습니다. Mac 보관소에서 확인하세요."
            return {"ok": True, "warning": warning, **self.public()}

    def route(self, task: str) -> dict | None:
        return self.get()["routing"].get(task)

    def save_routing(self, request: RoutingInput) -> dict:
        with self._lock:
            data = self.get()
            if data["revision"] != request.expected_revision:
                raise ProfileConflict("AI 설정이 변경되었습니다. 최신 설정을 확인한 뒤 다시 저장하세요.")
            data["routing"] = request.model_dump(exclude={"expected_revision"})
            data["revision"] += 1
            self._write(data)
            return self.public()
