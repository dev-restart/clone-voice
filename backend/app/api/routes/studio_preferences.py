"""Small, persisted product preferences; no model loading or credential handling."""
import platform
from threading import RLock
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.config import Settings, get_settings
from app.db.repositories import StudioSettingsRepository
from app.db.session import session_scope

router = APIRouter()
_lock = RLock()
_KEY = "studio-preferences:v1"


class StudioPreferences(BaseModel):
    start_menu: Literal["tts", "sfx", "changer", "home"] = "tts"
    source_language: Literal["ko", "en", "ja", "zh", "es", "fr", "de"] = "ko"
    stt_provider: Literal["apple-speech", "whisper"] = "apple-speech"
    show_auxiliary_tools: bool = False


def read_preferences(settings: Settings) -> StudioPreferences:
    with _lock, session_scope(settings) as session:
        raw = StudioSettingsRepository(session).get(_KEY)
        if raw:
            return StudioPreferences.model_validate(raw)
        return StudioPreferences(stt_provider="apple-speech" if platform.system() == "Darwin" else "whisper")


def response(preferences: StudioPreferences) -> dict:
    is_mac = platform.system() == "Darwin"
    return {
        "preferences": preferences.model_dump(),
        "platform": {
            "is_mac": is_mac,
            "apple_speech_supported": is_mac,
            "apple_speech_message": (
                "Apple 내장 음성 인식을 기본으로 사용합니다. 최초 사용에는 Mac의 음성 인식 권한과 언어 지원 확인이 필요합니다."
                if is_mac else "Apple 내장 음성 인식은 Mac에서 사용할 수 있습니다."
            ),
        },
        "generation_concurrency": 1,
    }


@router.get("/api/studio/preferences")
def get_preferences(settings: Settings = Depends(get_settings)):
    return response(read_preferences(settings))


@router.put("/api/studio/preferences")
def save_preferences(preferences: StudioPreferences, settings: Settings = Depends(get_settings)):
    with _lock, session_scope(settings) as session:
        StudioSettingsRepository(session).set(_KEY, preferences.model_dump())
    return response(preferences)
