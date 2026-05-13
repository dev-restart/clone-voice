from fastapi import Depends

from app.config import Settings, get_settings
from app.services.content_store import ContentStore
from app.services.model_router import ModelRouter, get_model_router
from app.services.voice_store import VoiceStore


def get_voice_store(settings: Settings = Depends(get_settings)) -> VoiceStore:
    return VoiceStore(settings.voices_dir, settings)


def get_content_store(settings: Settings = Depends(get_settings)) -> ContentStore:
    return ContentStore(settings.contents_dir, settings)


def get_router(settings: Settings = Depends(get_settings)) -> ModelRouter:
    return get_model_router(settings)
