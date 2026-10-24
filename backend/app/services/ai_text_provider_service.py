from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import Settings
from app.services.ai_text_connections import AiTextConnectionsStore, is_loopback_url, normalize_base_url
from app.services.apple_foundation_models_service import AppleFoundationModelsService
from app.services.ai_api_profiles import AiApiProfilesStore, is_api_profile, valid_provider
from app.services.ai_api_client import AiApiClient, validate_call


PROVIDER_APPLE = "apple"
APPLE_MODEL_ID = "apple-on-device"
PROVIDER_LOCAL = "local"
PROVIDER_CHATGPT = "chatgpt"
PROVIDER_KIMI = "kimi"
PROVIDER_NVIDIA = "nvidia"
PROVIDER_COMPATIBLE = "compatible"
SUPPORTED_PROVIDERS = (PROVIDER_APPLE, PROVIDER_LOCAL, PROVIDER_CHATGPT, PROVIDER_KIMI, PROVIDER_NVIDIA, PROVIDER_COMPATIBLE)

CHATGPT_MODELS = (
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna"},
)
KIMI_FALLBACK_MODELS = (
    {"id": "kimi-for-coding", "label": "Kimi K2.7 Coding"},
    {"id": "kimi-for-coding-highspeed", "label": "Kimi K2.7 HighSpeed"},
    {"id": "k3", "label": "Kimi K3"},
    {"id": "k3-256k", "label": "Kimi K3 256K"},
)
LOCAL_MAX_TOKENS_DEFAULT = 512
LOCAL_MAX_TOKENS_LIMIT = 4096


@dataclass(frozen=True)
class AiTextSelection:
    provider_id: str
    model_id: str


@dataclass(frozen=True)
class AiTextCompletion:
    content: str
    provider: str
    model: str


class AiTextSettingsStore:
    def __init__(self, path: Path, default_model: str):
        self.path = path.expanduser().resolve()
        self.default_model = default_model
        self._lock = threading.Lock()

    def get(self) -> AiTextSelection:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return AiTextSelection(PROVIDER_LOCAL, self.default_model)
        if not isinstance(payload, dict):
            return AiTextSelection(PROVIDER_LOCAL, self.default_model)
        provider_id = payload.get("provider_id", PROVIDER_LOCAL)
        model_id = payload.get("model_id", self.default_model)
        if not isinstance(provider_id, str) or not isinstance(model_id, str):
            return AiTextSelection(PROVIDER_LOCAL, self.default_model)
        provider_id, model_id = provider_id.strip(), model_id.strip()
        if not valid_provider(provider_id) or not model_id:
            return AiTextSelection(PROVIDER_LOCAL, self.default_model)
        return AiTextSelection(provider_id, model_id)

    def save(self, selection: AiTextSelection) -> AiTextSelection:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = {
            "provider_id": selection.provider_id,
            "model_id": selection.model_id,
        }
        with self._lock:
            try:
                with temporary.open("x", encoding="utf-8") as handle:
                    temporary.chmod(0o600)
                    handle.write(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        return selection


def _cli_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "CODEX_HOME",
        "KIMI_SHARE_DIR",
    )
    environment = {name: os.environ[name] for name in allowed if os.environ.get(name)}
    environment.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    environment.setdefault("HOME", str(Path.home()))
    environment["NO_COLOR"] = "1"
    return environment


def _resolve_cli(command: str) -> str | None:
    candidate = Path(command).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    resolved = shutil.which(command)
    if resolved:
        return resolved
    search_directories = [Path.home() / ".local/bin"]
    search_directories.extend(sorted((Path.home() / ".nvm/versions/node").glob("*/bin"), reverse=True))
    for directory in search_directories:
        path = directory / command
        if path.exists():
            return str(path)
    return None


def _compact_process_error(result: subprocess.CompletedProcess[str], label: str) -> RuntimeError:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        detail = re.sub(r"\s+", " ", detail)[:500]
        return RuntimeError(f"{label} 호출 실패: {detail}")
    return RuntimeError(f"{label} 호출이 종료 코드 {result.returncode}로 실패했습니다.")


def _parse_codex_message(stdout: str) -> str:
    message = ""
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            message = item["text"].strip()
    if not message:
        raise RuntimeError("Codex가 최종 text 응답을 반환하지 않았습니다.")
    return message


def _parse_kimi_message(stdout: str) -> str:
    message = ""
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("role") != "assistant":
            continue
        content = event.get("content")
        if isinstance(content, str) and content.strip():
            message = content.strip()
        elif isinstance(content, list):
            text_parts = [
                item["text"].strip()
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
            ]
            if text_parts:
                message = "\n".join(text_parts)
    if not message:
        raise RuntimeError("Kimi가 최종 text 응답을 반환하지 않았습니다.")
    return message


class AiTextProviderService:
    def __init__(self, settings: Settings, *, response_schema: dict | None = None):
        self.settings = settings
        self.response_schema = response_schema
        self.store = AiTextSettingsStore(settings.resolved_ai_text_settings_path, settings.llm_model)
        self.connections = AiTextConnectionsStore(settings)
        self.api_profiles = AiApiProfilesStore(settings)
        self._profile_snapshots: dict[str, dict] = {}
        self._profile_keys: dict[str, str] = {}

    def task_selection(self, task: str) -> AiTextSelection:
        route = self.api_profiles.route(task)
        return AiTextSelection(route["provider_id"], route["model_id"]) if route else self._selection()

    def _selection(self) -> AiTextSelection:
        selection = self.store.get()
        config = self.connections.get()
        if is_api_profile(selection.provider_id):
            # Keep the chosen identity visible; policy errors never silently reroute it.
            return selection
        if config["local_only"] and selection.provider_id not in {PROVIDER_APPLE, PROVIDER_LOCAL, PROVIDER_COMPATIBLE}:
            return AiTextSelection(PROVIDER_LOCAL, config["local"]["model_id"])
        if config["local_only"] and selection.provider_id == PROVIDER_COMPATIBLE and not is_loopback_url(config["compatible"]["base_url"]):
            return AiTextSelection(PROVIDER_LOCAL, config["local"]["model_id"])
        return selection

    def translation_selection(self, apple_status: dict | None = None) -> AiTextSelection:
        mode = self.connections.get()["translation_mode"]
        if mode == "selected":
            return self.task_selection("translation")
        status = apple_status if apple_status is not None else AppleFoundationModelsService(self.settings).status()
        if mode == "apple" or status["available"]:
            return AiTextSelection(PROVIDER_APPLE, APPLE_MODEL_ID)
        return self.task_selection("translation")

    def translation_status(self, apple_status: dict | None = None) -> dict:
        status = apple_status if apple_status is not None else AppleFoundationModelsService(self.settings).status()
        mode = self.connections.get()["translation_mode"]
        selection = self.translation_selection(status)
        if selection.provider_id == PROVIDER_APPLE:
            message = "번역을 Mac 내장 AI로 처리합니다. Ollama나 LM Studio 실행이 필요하지 않습니다." if status["available"] else status["message"]
        elif mode == "auto":
            message = "Mac 내장 AI를 사용할 수 없어 현재 선택한 텍스트 AI로 번역합니다."
        else:
            message = "현재 선택한 텍스트 AI로 번역합니다. 로컬 전용 설정이 동일하게 적용됩니다."
        return {"mode": mode, "effective_provider": selection.provider_id, "effective_model": selection.model_id,
                "message": message, "apple_available": bool(status["available"])}

    def _local_models(self) -> tuple[list[dict[str, str]], bool, str]:
        config = self.connections.get()
        try:
            base_url = normalize_base_url(config["local"]["base_url"])
        except ValueError:
            return [], False, "Ollama 주소가 올바르지 않습니다. 모델 설정에서 API 서버 주소를 수정하세요."
        if not is_loopback_url(base_url):
            return [], False, "Ollama는 localhost 주소로 연결해야 합니다."
        # Native model metadata distinguishes local weights from cloud aliases.
        parsed = urlsplit(base_url)
        tags_url = f"{parsed.scheme}://{parsed.netloc}/api/tags"
        request = urllib.request.Request(
            tags_url,
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.settings.llm_timeout_seconds, 5)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = [
                {"id": item["name"], "label": item["name"]}
                for item in payload.get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
                and not item.get("remote_model") and not item.get("remote_host")
                and "cloud" not in item["name"].lower()
                and item.get("size", 0) > 0
            ]
            return models, bool(models), "이 컴퓨터에 내려받은 Ollama 모델을 사용합니다." if models else "Ollama는 연결됐지만 로컬 모델이 없습니다. 모델을 먼저 내려받으세요."
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return (
                [],
                False,
                "Ollama에 연결할 수 없습니다. Ollama 실행과 서버 주소를 확인하세요.",
            )

    def _chatgpt_status(self) -> tuple[bool, str, str | None]:
        binary = _resolve_cli(self.settings.codex_cli_bin)
        if not binary:
            return False, "Codex CLI가 설치되어 있지 않습니다.", None
        try:
            result = subprocess.run(
                [binary, "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                env=_cli_environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "Codex 로그인 상태를 확인하지 못했습니다.", binary
        connected = result.returncode == 0 and "logged in" in f"{result.stdout}\n{result.stderr}".lower()
        return connected, "ChatGPT 구독 계정이 연결되어 있습니다." if connected else "ChatGPT 계정 로그인이 필요합니다.", binary

    def _kimi_models(self) -> list[dict[str, str]]:
        config_path = Path(os.environ.get("KIMI_SHARE_DIR", Path.home() / ".kimi")) / "config.toml"
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            models = []
            for alias, value in config.get("models", {}).items():
                if not isinstance(value, dict) or not str(alias).startswith("kimi-code/"):
                    continue
                model_id = str(value.get("model") or str(alias).split("/", 1)[-1]).strip()
                if model_id:
                    models.append({"id": model_id, "label": str(value.get("display_name") or model_id)})
            if models:
                return models
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError, AttributeError):
            pass
        return [dict(model) for model in KIMI_FALLBACK_MODELS]

    def _kimi_status(self) -> tuple[bool, str, str | None]:
        binary = _resolve_cli(self.settings.kimi_cli_bin)
        if not binary:
            return False, "Kimi CLI가 설치되어 있지 않습니다.", None
        share_dir = Path(os.environ.get("KIMI_SHARE_DIR", Path.home() / ".kimi"))
        connected = (share_dir / "credentials/kimi-code.json").exists()
        return connected, "Kimi 구독 계정이 연결되어 있습니다." if connected else "Kimi 계정 로그인이 필요합니다.", binary

    def catalog(self) -> dict[str, object]:
        selection = self._selection()
        config = self.connections.get()
        local_models, local_available, local_message = self._local_models()
        apple_status = AppleFoundationModelsService(self.settings).status()
        if config["local_only"]:
            chatgpt_available, chatgpt_message, chatgpt_binary = False, "로컬 전용에서는 외부 AI를 사용하지 않습니다.", None
            kimi_available, kimi_message, kimi_binary = False, chatgpt_message, None
        else:
            chatgpt_available, chatgpt_message, chatgpt_binary = self._chatgpt_status()
            kimi_available, kimi_message, kimi_binary = self._kimi_status()
        providers = [
            {
                "id": PROVIDER_LOCAL,
                "label": "로컬 Ollama",
                "connection_type": "local",
                "available": local_available,
                "authenticated": local_available,
                "message": local_message,
                "models": local_models,
            },
            {
                "id": PROVIDER_CHATGPT,
                "label": "ChatGPT · Codex 연결",
                "connection_type": "subscription",
                "available": chatgpt_available,
                "authenticated": chatgpt_available,
                "message": chatgpt_message,
                "runtime": chatgpt_binary,
                "models": [dict(model) for model in CHATGPT_MODELS],
            },
            {
                "id": PROVIDER_KIMI,
                "label": "Kimi 구독",
                "connection_type": "subscription",
                "available": kimi_available,
                "authenticated": kimi_available,
                "message": kimi_message,
                "runtime": kimi_binary,
                "models": self._kimi_models(),
            },
        ]
        providers.append({
            "id": PROVIDER_APPLE,
            "label": "Apple 내장 AI",
            "connection_type": "local",
            "available": bool(apple_status["available"]),
            "authenticated": bool(apple_status["available"]),
            "message": apple_status["message"],
            "models": [{"id": APPLE_MODEL_ID, "label": "Mac 온디바이스 모델"}],
        })
        return {
            "translation": self.translation_status(apple_status),
            "selection": {"provider_id": selection.provider_id, "model_id": selection.model_id},
            "providers": providers,
            "api_providers": [self._api_provider(provider_id, config) for provider_id in (PROVIDER_COMPATIBLE, PROVIDER_NVIDIA)] + self.profile_catalog(),
            "connections": self.connections.public(),
        }

    def profile_catalog(self) -> list[dict]:
        profiles = self.api_profiles.public()["profiles"]
        return [{"id": p["id"], "label": p["name"], "connection_type": "local" if p["local"] else "api",
                 "available": p["enabled"] and not p["blocked"] and bool(p["models"]) and (p["auth_type"] == "none" or p["has_api_key"]),
                 "authenticated": False, "status": p["status"],
                 "message": "등록된 연결입니다. 실제 모델 응답은 별도 테스트로 확인하세요." if not p["blocked"] else "로컬 전용 설정으로 차단되었습니다.",
                 "models": [{"id": m["id"], "label": m["label"] or m["id"]} for m in p["models"]]} for p in profiles]

    def validate_profile_selection(self, provider_id: str, model_id: str) -> None:
        profile = self.api_profiles.find(provider_id)
        validate_call(profile, self.connections.get()["local_only"])
        if not any(m["id"] == model_id for m in profile["models"]):
            raise ValueError("이 연결에 등록된 모델을 선택하세요.")
        if profile["auth_type"] != "none" and not self.api_profiles.public_profile(profile)["has_api_key"]:
            raise ValueError("API 키를 먼저 등록하세요.")

    def _api_provider(self, provider_id: str, config: dict) -> dict:
        values = config[provider_id]
        try:
            normalize_base_url(values["base_url"])
            valid_url = True
        except ValueError:
            valid_url = False
        local = is_loopback_url(values["base_url"])
        blocked = config["local_only"] and not local
        configured = bool(valid_url and values["model_id"] and (provider_id != PROVIDER_NVIDIA or values["api_key"]))
        return {
            "id": provider_id,
            "label": "NVIDIA API" if provider_id == PROVIDER_NVIDIA else "OpenAI-compatible 서버",
            "connection_type": "local" if local else "api",
            "available": configured and not blocked,
            "authenticated": bool(values["api_key"]),
            "message": "API 서버 주소를 수정하세요." if not valid_url else "로컬 전용을 해제하면 외부 API를 선택할 수 있습니다." if blocked else (
                "연결 설정을 저장했습니다. 연결 확인으로 실제 응답을 확인하세요." if configured else "서버 주소와 모델을 설정하세요. NVIDIA API에는 API key도 필요합니다."
            ),
            "models": [{"id": values["model_id"], "label": values["model_id"]}] if values["model_id"] else [],
        }

    def update_connection(self, changes: dict) -> dict:
        self.connections.update(changes)
        # Returning to local-only must not later resurrect a previous cloud selection.
        selection = self._selection()
        self.store.save(selection)
        return self.catalog()

    def save_selection(self, provider_id: str, model_id: str) -> AiTextSelection:
        if is_api_profile(provider_id):
            with AiApiProfilesStore._lock:
                try:
                    self.validate_profile_selection(provider_id, model_id)
                except KeyError as exc:
                    raise ValueError("AI 연결을 찾을 수 없습니다.") from exc
                return self.store.save(AiTextSelection(provider_id, model_id))
        catalog = self.catalog()
        provider = next((item for item in [*catalog["providers"], *catalog["api_providers"]] if item["id"] == provider_id), None)
        if not provider:
            raise ValueError(f"지원하지 않는 AI provider입니다: {provider_id}")
        config = self.connections.get()
        external = provider_id in {PROVIDER_CHATGPT, PROVIDER_KIMI, PROVIDER_NVIDIA} or (
            provider_id == PROVIDER_COMPATIBLE and not is_loopback_url(config["compatible"]["base_url"])
        )
        if external and config["local_only"]:
            # An explicit provider selection is also the opt-in for API clients
            # using the original selection contract. Merely reading status or
            # generating text never enables external processing.
            if provider_id == PROVIDER_CHATGPT:
                available, message, _ = self._chatgpt_status()
                provider = {**provider, "available": available, "message": message}
            elif provider_id == PROVIDER_KIMI:
                available, message, _ = self._kimi_status()
                provider = {**provider, "available": available, "message": message}
            else:
                provider = self._api_provider(provider_id, {**config, "local_only": False})
        if not provider["available"]:
            raise RuntimeError(str(provider["message"]))
        if not any(model["id"] == model_id for model in provider["models"]):
            raise ValueError(f"지원하지 않는 AI model입니다: {provider_id}/{model_id}")
        if external and config["local_only"]:
            self.connections.update({"local_only": False})
        return self.store.save(AiTextSelection(provider_id, model_id))

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        max_tokens: int | None = None,
        task: str = "writing",
    ) -> AiTextCompletion:
        selection = self.task_selection(task)
        provider = provider_id or selection.provider_id
        model = model_id or selection.model_id
        config = self.connections.get()
        if is_api_profile(provider):
            try:
                with AiApiProfilesStore._lock:
                    latest_profile = self.api_profiles.find(provider)
                    validate_call(latest_profile, config["local_only"])
                    if provider not in self._profile_snapshots:
                        self._profile_snapshots[provider] = latest_profile
                        self._profile_keys[provider] = self.api_profiles.key(latest_profile)
                profile = self._profile_snapshots[provider]
                validate_call(profile, config["local_only"])
                # Fix the destination AND credential for this request; key rotation
                # cannot switch a multi-chunk translation halfway through.
                key = self._profile_keys[provider]
                def guard():
                    current_policy = self.connections.get()["local_only"]
                    validate_call(self.api_profiles.find(provider), current_policy)
                    validate_call(profile, current_policy)
                content = AiApiClient(profile, key, scope=str(self.api_profiles.path.absolute()), local_only=config["local_only"], before_request=guard).complete(
                    prompt, system_prompt, model, max_tokens=max_tokens, schema=self.response_schema)
                return AiTextCompletion(content, provider, model)
            except KeyError as exc:
                raise RuntimeError("AI 연결이 삭제되었거나 존재하지 않습니다. 설정에서 다른 연결을 선택하세요.") from exc
        if config["local_only"] and provider not in {PROVIDER_APPLE, PROVIDER_LOCAL} and not (
            provider == PROVIDER_COMPATIBLE and is_loopback_url(config["compatible"]["base_url"])
        ):
            raise RuntimeError("로컬 전용이 켜져 있어 외부 AI 호출을 차단했습니다.")
        if len(prompt.encode("utf-8")) > 128 * 1024:
            raise RuntimeError("AI Prompt가 허용 크기를 초과했습니다.")
        if provider == PROVIDER_APPLE:
            if model != APPLE_MODEL_ID:
                raise RuntimeError("Apple 내장 AI는 Mac 온디바이스 모델을 사용해야 합니다.")
            if self.response_schema is not None:
                system_prompt = f"{system_prompt}\nReturn JSON matching this schema exactly:\n{json.dumps(self.response_schema, ensure_ascii=False)}"
            content = AppleFoundationModelsService(self.settings).complete(prompt, system_prompt=system_prompt, max_tokens=max_tokens)
            return AiTextCompletion(content, PROVIDER_APPLE, APPLE_MODEL_ID)
        if provider == PROVIDER_LOCAL:
            return self._complete_local(prompt, system_prompt, model, max_tokens=max_tokens)
        if provider == PROVIDER_CHATGPT:
            return self._complete_chatgpt(prompt, system_prompt, model)
        if provider == PROVIDER_KIMI:
            return self._complete_kimi(prompt, system_prompt, model)
        if provider in {PROVIDER_NVIDIA, PROVIDER_COMPATIBLE}:
            values = config[provider]
            if not model.strip() or (provider == PROVIDER_NVIDIA and not values["api_key"]):
                raise RuntimeError("외부 API의 모델과 API key를 설정하세요.")
            return self._complete_api(prompt, system_prompt, model, provider=provider, base_url=values["base_url"], api_key=values["api_key"], max_tokens=max_tokens)
        raise RuntimeError(f"지원하지 않는 AI provider입니다: {provider}")

    def _complete_local(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        *,
        max_tokens: int | None = None,
    ) -> AiTextCompletion:
        config = self.connections.get()
        base_url = normalize_base_url(config["local"]["base_url"])
        if not is_loopback_url(base_url) or "cloud" in model.lower():
            raise RuntimeError("로컬 Ollama에는 이 컴퓨터에 내려받은 모델만 사용할 수 있습니다.")
        parsed = urlsplit(base_url)
        show_request = urllib.request.Request(
            f"{parsed.scheme}://{parsed.netloc}/api/show",
            data=json.dumps({"model": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(show_request, timeout=min(self.settings.llm_timeout_seconds, 5)) as response:
                metadata = json.loads(response.read().decode("utf-8"))
            if metadata.get("remote_model") or metadata.get("remote_host"):
                raise RuntimeError("Ollama cloud 모델은 로컬 전용에서 사용할 수 없습니다.")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError) as exc:
            raise RuntimeError("Ollama 모델을 확인할 수 없습니다. 모델 설치와 실행 상태를 확인하세요.") from exc
        return self._complete_api(prompt, system_prompt, model, provider=PROVIDER_LOCAL, base_url=base_url, api_key=self.settings.llm_api_key, max_tokens=max_tokens)

    def _complete_api(
        self, prompt: str, system_prompt: str, model: str, *, provider: str,
        base_url: str, api_key: str, max_tokens: int | None = None,
    ) -> AiTextCompletion:
        resolved_max_tokens = LOCAL_MAX_TOKENS_DEFAULT
        if max_tokens is not None:
            resolved_max_tokens = min(max(int(max_tokens), 1), LOCAL_MAX_TOKENS_LIMIT)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": resolved_max_tokens,
        }
        if provider == PROVIDER_LOCAL:
            body["reasoning_effort"] = "none"
            if self.response_schema is not None:
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "voice_production", "strict": True, "schema": self.response_schema}}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            f"{normalize_base_url(base_url)}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            # Never return an upstream response body containing tokens or prompts.
            raise RuntimeError(f"AI 모델 호출에 실패했습니다 ({provider}): {type(exc).__name__}") from exc
        if payload["choices"][0].get("finish_reason") == "length":
            raise RuntimeError("AI 응답이 출력 길이 제한에 도달했습니다. 대담 길이나 자료 분량을 줄여 다시 생성하세요.")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("AI 모델이 빈 응답을 반환했습니다. 모델과 출력 길이를 확인하세요.")
        return AiTextCompletion(content.strip(), provider, model)

    def _complete_chatgpt(self, prompt: str, system_prompt: str, model: str) -> AiTextCompletion:
        binary = _resolve_cli(self.settings.codex_cli_bin)
        if not binary:
            raise RuntimeError("Codex CLI가 설치되어 있지 않습니다.")
        with tempfile.TemporaryDirectory(prefix="clone-voice-codex-") as workdir:
            developer_instructions = json.dumps(system_prompt.strip(), ensure_ascii=False)
            command = [
                binary,
                "exec",
                "--json",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "--strict-config",
                "--config",
                f"developer_instructions={developer_instructions}",
                "--disable",
                "shell_tool",
                "-m",
                model,
                "-C",
                workdir,
                "-",
            ]
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.ai_cli_timeout_seconds,
                    env=_cli_environment(),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("ChatGPT 구독 모델 호출 시간이 초과되었습니다.") from exc
            if result.returncode != 0:
                raise _compact_process_error(result, "ChatGPT 구독 모델")
            return AiTextCompletion(_parse_codex_message(result.stdout), PROVIDER_CHATGPT, model)

    def _complete_kimi(self, prompt: str, system_prompt: str, model: str) -> AiTextCompletion:
        binary = _resolve_cli(self.settings.kimi_cli_bin)
        if not binary:
            raise RuntimeError("Kimi CLI가 설치되어 있지 않습니다.")
        with tempfile.TemporaryDirectory(prefix="clone-voice-kimi-") as workdir:
            workdir_path = Path(workdir)
            system_path = workdir_path / "system.md"
            agent_path = workdir_path / "agent.yaml"
            system_path.write_text(system_prompt.strip(), encoding="utf-8")
            agent_path.write_text(
                "version: 1\n"
                "agent:\n"
                "  name: clone-voice-text\n"
                "  system_prompt_path: ./system.md\n"
                "  tools: []\n",
                encoding="utf-8",
            )
            command = [
                binary,
                "--print",
                "--output-format",
                "stream-json",
                "--model",
                f"kimi-code/{model}",
                "--agent-file",
                str(agent_path),
                "--max-steps-per-turn",
                "1",
                "--max-retries-per-step",
                "1",
                "--work-dir",
                workdir,
            ]
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.ai_cli_timeout_seconds,
                    env=_cli_environment(),
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Kimi 구독 모델 호출 시간이 초과되었습니다.") from exc
            if result.returncode != 0:
                raise _compact_process_error(result, "Kimi 구독 모델")
            return AiTextCompletion(_parse_kimi_message(result.stdout), PROVIDER_KIMI, model)


@dataclass
class _LoginSession:
    id: str
    provider_id: str
    process: subprocess.Popen[str]
    output: str = ""
    authorization_url: str | None = None
    user_code: str | None = None
    status: str = "running"
    message: str = "인증을 기다리고 있습니다."


_login_sessions: dict[str, _LoginSession] = {}
_login_lock = threading.Lock()


def _login_details(output: str) -> tuple[str | None, str | None]:
    url_match = re.search(r"https?://[^\s\"']+", output)
    code_match = re.search(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4})+\b", output)
    authorization_url = url_match.group(0).rstrip(".,)") if url_match else None
    user_code = code_match.group(0) if code_match else None
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        url = event.get("verification_uri") or event.get("verificationUri") or event.get("url")
        code = event.get("user_code") or event.get("userCode") or event.get("code")
        if isinstance(url, str) and url.startswith("http"):
            authorization_url = url
        if isinstance(code, str) and code:
            user_code = code
    return authorization_url, user_code


def _consume_login_session(session: _LoginSession) -> None:
    assert session.process.stdout is not None
    for line in session.process.stdout:
        with _login_lock:
            session.output = (session.output + line)[-20_000:]
            session.authorization_url, session.user_code = _login_details(session.output)
    return_code = session.process.wait()
    with _login_lock:
        session.status = "complete" if return_code == 0 else "error"
        session.message = "계정 연결이 완료되었습니다." if return_code == 0 else "계정 연결에 실패했습니다. 다시 시도해 주세요."


def start_provider_login(settings: Settings, provider_id: str) -> dict[str, object]:
    if provider_id == PROVIDER_CHATGPT:
        binary = _resolve_cli(settings.codex_cli_bin)
        command = [binary, "login", "--device-auth"] if binary else None
    elif provider_id == PROVIDER_KIMI:
        binary = _resolve_cli(settings.kimi_cli_bin)
        command = [binary, "login", "--json"] if binary else None
    else:
        raise ValueError("로컬 provider는 계정 로그인이 필요하지 않습니다.")
    if not command:
        raise RuntimeError("로그인에 필요한 CLI가 설치되어 있지 않습니다.")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_cli_environment(),
        bufsize=1,
    )
    session = _LoginSession(id=uuid4().hex, provider_id=provider_id, process=process)
    with _login_lock:
        _login_sessions[session.id] = session
    threading.Thread(target=_consume_login_session, args=(session,), daemon=True).start()
    for _ in range(20):
        time.sleep(0.1)
        with _login_lock:
            if session.authorization_url or session.status != "running":
                break
    return get_provider_login(session.id)


def get_provider_login(session_id: str) -> dict[str, object]:
    with _login_lock:
        session = _login_sessions.get(session_id)
        if not session:
            raise KeyError("계정 연결 session을 찾을 수 없습니다.")
        return {
            "id": session.id,
            "provider_id": session.provider_id,
            "status": session.status,
            "authorization_url": session.authorization_url,
            "user_code": session.user_code,
            "message": session.message,
        }
