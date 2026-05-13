from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings
from app.db.repositories import StudioSettingsRepository
from app.db.session import session_scope
from app.schemas import (
    ModelPreference,
    ModelPreferencesResponse,
    ModelPreferencesUpdateRequest,
    RuntimeModelStatus,
)

MODEL_PREFERENCES_KEY = "model_display_preferences"
DEFAULT_MODEL_ORDER = {
    "omnivoice": 10,
    "voxcpm": 20,
    "cosyvoice": 30,
    "seed-vc": 40,
}


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


def normalize_model_preferences(
    models: list[RuntimeModelStatus],
    settings: Settings,
    stored: dict | None = None,
    override_preferences: dict[str, ModelPreference] | None = None,
    override_default_tts_model: str | None = None,
    override_default_vc_model: str | None = None,
) -> ModelPreferencesResponse:
    stored_preferences = _stored_preferences_to_dict(stored)
    source_preferences = override_preferences if override_preferences is not None else stored_preferences
    known_ids = {model.id for model in models}
    preferences: dict[str, ModelPreference] = {}
    for index, model in enumerate(models):
        preference = source_preferences.get(model.id)
        preferences[model.id] = ModelPreference(
            id=model.id,
            enabled=preference.enabled if preference else True,
            order=_coerce_order(preference.order if preference else None, _default_order(model, index)),
        )

    ordered_models = sorted(models, key=lambda model: (preferences[model.id].order, model.label))
    active_tts_models = [model for model in ordered_models if model.capabilities.tts and preferences[model.id].enabled]
    if not active_tts_models:
        first_tts_model = next((model for model in ordered_models if model.capabilities.tts), None)
        if first_tts_model:
            preferences[first_tts_model.id] = ModelPreference(
                id=first_tts_model.id,
                enabled=True,
                order=preferences[first_tts_model.id].order,
            )
            active_tts_models = [first_tts_model]

    stored_default_tts_model = stored.get("default_tts_model") if isinstance(stored, dict) else None
    stored_default_vc_model = stored.get("default_vc_model") if isinstance(stored, dict) else None
    default_tts_model = override_default_tts_model or stored_default_tts_model or settings.default_tts_model
    default_vc_model = override_default_vc_model or stored_default_vc_model or settings.default_vc_model

    if default_tts_model not in {model.id for model in active_tts_models}:
        default_tts_model = (
            next((model.id for model in active_tts_models if model.status == "available"), None)
            or (active_tts_models[0].id if active_tts_models else "")
        )
    if default_vc_model not in known_ids:
        default_vc_model = next((model.id for model in ordered_models if model.capabilities.voice_conversion), None) or ""

    return ModelPreferencesResponse(
        model_preferences=preferences,
        default_tts_model=default_tts_model,
        default_vc_model=default_vc_model,
    )


def model_preferences_to_storage(response: ModelPreferencesResponse) -> dict:
    return {
        "model_preferences": {
            model_id: preference.model_dump(mode="json")
            for model_id, preference in response.model_preferences.items()
        },
        "default_tts_model": response.default_tts_model,
        "default_vc_model": response.default_vc_model,
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
    if request.default_tts_model and request.default_tts_model not in known_models:
        raise HTTPException(status_code=422, detail=f"Unknown default TTS model: {request.default_tts_model}")
    if request.default_tts_model and not known_models[request.default_tts_model].capabilities.tts:
        raise HTTPException(status_code=422, detail=f"{request.default_tts_model} does not support TTS")

    merged_preferences: dict[str, ModelPreference] = {}
    for index, model in enumerate(models):
        requested = request.model_preferences.get(model.id)
        merged_preferences[model.id] = ModelPreference(
            id=model.id,
            enabled=requested.enabled if requested else True,
            order=_coerce_order(requested.order if requested else None, _default_order(model, index)),
        )

    if any(model.capabilities.tts for model in models) and not any(model.capabilities.tts and merged_preferences[model.id].enabled for model in models):
        raise HTTPException(status_code=422, detail="At least one TTS-capable model must remain enabled.")

    with session_scope(settings) as session:
        repository = StudioSettingsRepository(session)
        stored = repository.get(MODEL_PREFERENCES_KEY)
        response = normalize_model_preferences(
            models,
            settings,
            stored=stored,
            override_preferences=merged_preferences,
            override_default_tts_model=request.default_tts_model,
            override_default_vc_model=request.default_vc_model,
        )
        repository.set(MODEL_PREFERENCES_KEY, model_preferences_to_storage(response))
    return response
