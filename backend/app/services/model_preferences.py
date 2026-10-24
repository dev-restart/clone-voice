from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings
from app.db.repositories import StudioSettingsRepository
from app.db.session import session_scope
from app.schemas import (
    MODEL_DOMAINS,
    ModelDomain,
    ModelPreference,
    ModelPreferencesResponse,
    ModelPreferencesUpdateRequest,
    RuntimeModelStatus,
)
from app.services.model_router import DOMAIN_CAPABILITY

MODEL_PREFERENCES_KEY = "model_display_preferences"
DEFAULT_MODEL_ORDER = {
    "voxcpm": 10,
    "soulx-singer": 20,
    "stable-audio-sfx": 30,
}
# Older clients and stored rows only know these two defaults.
LEGACY_DEFAULT_KEYS: dict[str, ModelDomain] = {"default_tts_model": "voice", "default_vc_model": "cover"}
SUPPORT_LABEL = {"voice": "TTS", "music": "music generation", "cover": "voice conversion", "sfx": "sound-effect generation"}
# Voice and cover always need a usable model; music and sound effects may be switched off entirely.
REQUIRED_LABEL: dict[ModelDomain, str] = {"voice": "TTS-capable", "cover": "voice-conversion"}


def _supports(model: RuntimeModelStatus, domain: ModelDomain) -> bool:
    return bool(getattr(model.capabilities, DOMAIN_CAPABILITY[domain], False))


def _default_order(model: RuntimeModelStatus, index: int) -> int:
    return DEFAULT_MODEL_ORDER.get(model.id, 100 + index)


def _coerce_order(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _stored_preferences_to_dict(stored: dict | None) -> dict[str, ModelPreference]:
    if not stored:
        return {}
    raw_preferences = stored.get("model_preferences", {})
    if not isinstance(raw_preferences, dict):
        return {}
    preferences: dict[str, ModelPreference] = {}
    for model_id, raw in raw_preferences.items():
        if not model_id or not isinstance(raw, dict):
            continue
        preferences[model_id] = ModelPreference(
            id=model_id,
            enabled=raw.get("enabled", True) is not False,
            order=_coerce_order(raw.get("order"), 100 + len(preferences)),
        )
    return preferences


def _stored_defaults(stored: dict | None) -> dict[ModelDomain, str]:
    if not isinstance(stored, dict):
        return {}
    defaults: dict[ModelDomain, str] = {}
    for legacy_key, domain in LEGACY_DEFAULT_KEYS.items():
        value = stored.get(legacy_key)
        if isinstance(value, str) and value:
            defaults[domain] = value
    raw = stored.get("default_models")
    if isinstance(raw, dict):
        for domain in MODEL_DOMAINS:
            value = raw.get(domain)
            if isinstance(value, str) and value:
                defaults[domain] = value
    return defaults


def _configured_default(settings: Settings, domain: ModelDomain) -> str:
    return {
        "voice": settings.default_tts_model,
        "cover": settings.default_vc_model,
        "sfx": settings.default_sfx_model,
        "music": settings.default_music_model,
    }[domain]


def normalize_model_preferences(
    models: list[RuntimeModelStatus],
    settings: Settings,
    stored: dict | None = None,
    override_preferences: dict[str, ModelPreference] | None = None,
    override_defaults: dict[ModelDomain, str] | None = None,
) -> ModelPreferencesResponse:
    source_preferences = override_preferences if override_preferences is not None else _stored_preferences_to_dict(stored)
    preferences: dict[str, ModelPreference] = {}
    for index, model in enumerate(models):
        preference = source_preferences.get(model.id)
        preferences[model.id] = ModelPreference(
            id=model.id,
            enabled=preference.enabled if preference else True,
            order=_coerce_order(preference.order if preference else None, _default_order(model, index)),
        )
    ordered_models = sorted(models, key=lambda model: (preferences[model.id].order, model.label))

    stored_defaults = _stored_defaults(stored)
    defaults: dict[ModelDomain, str] = {}
    for domain in MODEL_DOMAINS:
        domain_models = [model for model in ordered_models if _supports(model, domain)]
        if not domain_models:
            continue
        active = [model for model in domain_models if preferences[model.id].enabled]
        if not active and domain in REQUIRED_LABEL:
            first = domain_models[0]
            preferences[first.id] = ModelPreference(id=first.id, enabled=True, order=preferences[first.id].order)
            active = [first]
        if not active:
            continue
        wanted = (override_defaults or {}).get(domain) or stored_defaults.get(domain) or _configured_default(settings, domain)
        if wanted not in {model.id for model in active}:
            wanted = next((model.id for model in active if model.status == "available"), None) or active[0].id
        defaults[domain] = wanted

    return ModelPreferencesResponse(
        model_preferences=preferences,
        default_tts_model=defaults.get("voice", ""),
        default_vc_model=defaults.get("cover", ""),
        default_models=defaults,
    )


def model_preferences_to_storage(response: ModelPreferencesResponse) -> dict:
    return {
        "model_preferences": {
            model_id: preference.model_dump(mode="json")
            for model_id, preference in response.model_preferences.items()
        },
        "default_tts_model": response.default_tts_model,
        "default_vc_model": response.default_vc_model,
        "default_models": dict(response.default_models),
    }


def get_model_preferences(settings: Settings, models: list[RuntimeModelStatus], *, persist_default: bool = False) -> ModelPreferencesResponse:
    with session_scope(settings) as session:
        repository = StudioSettingsRepository(session)
        stored = repository.get(MODEL_PREFERENCES_KEY)
        response = normalize_model_preferences(models, settings, stored=stored)
        if persist_default or stored is None:
            repository.set(MODEL_PREFERENCES_KEY, model_preferences_to_storage(response))
        return response


def save_model_preferences(
    settings: Settings,
    models: list[RuntimeModelStatus],
    request: ModelPreferencesUpdateRequest,
) -> ModelPreferencesResponse:
    known_models = {model.id: model for model in models}
    unknown_ids = sorted(set(request.model_preferences) - set(known_models))
    if unknown_ids:
        raise HTTPException(status_code=422, detail=f"Unknown model preference id: {', '.join(unknown_ids)}")

    requested_defaults: dict[ModelDomain, str] = dict(request.default_models)
    if request.default_tts_model:
        requested_defaults.setdefault("voice", request.default_tts_model)
    if request.default_vc_model:
        requested_defaults.setdefault("cover", request.default_vc_model)
    for domain, model_id in requested_defaults.items():
        if model_id not in known_models:
            raise HTTPException(status_code=422, detail=f"Unknown default {SUPPORT_LABEL[domain]} model: {model_id}")
        if not _supports(known_models[model_id], domain):
            raise HTTPException(status_code=422, detail=f"{model_id} does not support {SUPPORT_LABEL[domain]}")

    merged_preferences: dict[str, ModelPreference] = {}
    for index, model in enumerate(models):
        requested = request.model_preferences.get(model.id)
        merged_preferences[model.id] = ModelPreference(
            id=model.id,
            enabled=requested.enabled if requested else True,
            order=_coerce_order(requested.order if requested else None, _default_order(model, index)),
        )
    for domain, required_label in REQUIRED_LABEL.items():
        domain_models = [model for model in models if _supports(model, domain)]
        if domain_models and not any(merged_preferences[model.id].enabled for model in domain_models):
            raise HTTPException(status_code=422, detail=f"At least one {required_label} model must remain enabled.")

    with session_scope(settings) as session:
        repository = StudioSettingsRepository(session)
        stored = repository.get(MODEL_PREFERENCES_KEY)
        response = normalize_model_preferences(
            models,
            settings,
            stored=stored,
            override_preferences=merged_preferences,
            override_defaults=requested_defaults,
        )
        repository.set(MODEL_PREFERENCES_KEY, model_preferences_to_storage(response))
    return response
