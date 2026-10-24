from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import Settings


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def is_loopback_url(value: str) -> bool:
    try:
        return urlsplit(normalize_base_url(value)).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def normalize_base_url(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    if any(character in cleaned for character in ("\r", "\n", "\t")):
        raise ValueError("API 주소에는 제어 문자를 사용할 수 없습니다.")
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API 주소는 인증 정보 없는 http 또는 https URL이어야 합니다.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("API 주소의 port가 올바르지 않습니다.") from exc
    return cleaned


class AiTextConnectionsStore:
    """Keep credentials on the backend; public settings contain presence flags only."""

    _lock = threading.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.resolved_ai_text_settings_path.with_name("ai_text_connections.json")

    def get(self) -> dict:
        defaults = {
            "local_only": True,
            "translation_mode": "auto",
            "local": {"base_url": self.settings.llm_base_url, "model_id": self.settings.llm_model},
            "nvidia": {"base_url": NVIDIA_BASE_URL, "model_id": "", "api_key": ""},
            "compatible": {"base_url": "http://127.0.0.1:1234/v1", "model_id": "", "api_key": ""},
        }
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return defaults
        if not isinstance(stored, dict):
            return defaults
        defaults["local_only"] = stored.get("local_only", True) is not False
        if stored.get("translation_mode") in {"auto", "apple", "selected"}:
            defaults["translation_mode"] = stored["translation_mode"]
        for provider_id in ("local", "nvidia", "compatible"):
            values = stored.get(provider_id)
            if isinstance(values, dict):
                for key in defaults[provider_id]:
                    if isinstance(values.get(key), str):
                        defaults[provider_id][key] = values[key]
        # NVIDIA's hosted endpoint is fixed. Self-hosted NIM uses compatible.
        defaults["nvidia"]["base_url"] = NVIDIA_BASE_URL
        return defaults

    def public(self) -> dict:
        config = self.get()
        public_urls = {}
        for provider_id in ("local", "nvidia", "compatible"):
            try:
                public_urls[provider_id] = normalize_base_url(config[provider_id]["base_url"])
            except ValueError:
                # A hand-edited URL may embed credentials. Never echo it to the browser.
                public_urls[provider_id] = ""
        return {
            "local_only": config["local_only"],
            "translation_mode": config["translation_mode"],
            **{
                provider_id: {
                    "base_url": public_urls[provider_id],
                    "model_id": config[provider_id]["model_id"],
                    "has_api_key": bool(config[provider_id].get("api_key")),
                }
                for provider_id in ("local", "nvidia", "compatible")
            },
        }

    def update(self, changes: dict) -> dict:
        with self._lock:
            config = self.get()
            if changes.get("local_only") is not None:
                config["local_only"] = changes["local_only"]
            if changes.get("translation_mode") is not None:
                if changes["translation_mode"] not in {"auto", "apple", "selected"}:
                    raise ValueError("지원하지 않는 번역 엔진 설정입니다.")
                config["translation_mode"] = changes["translation_mode"]
            provider_id = changes.get("provider_id")
            if provider_id:
                if provider_id not in ("local", "nvidia", "compatible"):
                    raise ValueError("지원하지 않는 API 연결입니다.")
                values = config[provider_id]
                if changes.get("base_url") is not None:
                    base_url = normalize_base_url(changes["base_url"])
                    if provider_id == "nvidia" and base_url != NVIDIA_BASE_URL:
                        raise ValueError("자체 NIM 서버는 OpenAI-compatible 연결을 사용하세요.")
                    if provider_id == "local" and not is_loopback_url(base_url):
                        raise ValueError("Ollama 주소는 이 컴퓨터의 localhost 주소를 사용하세요.")
                    if provider_id == "compatible" and config["local_only"] and not is_loopback_url(base_url):
                        raise ValueError("외부 서버를 설정하려면 로컬 전용을 먼저 해제하세요.")
                    values["base_url"] = base_url
                if changes.get("model_id") is not None:
                    values["model_id"] = changes["model_id"].strip()
                if changes.get("api_key") is not None:
                    values["api_key"] = changes["api_key"].strip()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            try:
                with temporary.open("x", encoding="utf-8") as handle:
                    temporary.chmod(0o600)
                    handle.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        return self.public()
