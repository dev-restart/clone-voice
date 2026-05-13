from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    audio,
    contents,
    files,
    generation_preview,
    health,
    models,
    settings,
    speech,
    story,
    tts,
    voice_conversion,
    voices,
    websocket,
)
from app.api.deps import get_router
from app.config import get_settings
from app.services.generation_helpers import transcribe_with_segments
from app.services.youtube_import_service import import_youtube_audio

runtime_settings = get_settings()

app = FastAPI(
    title=runtime_settings.app_name,
    version="0.1.0",
    summary="Local-first AI voice production API",
    description=(
        "Backend API for Clone Voice Studio. It manages voice profiles, TTS generation, "
        "speech transcription, story audio, voice conversion, generated files, and model health."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=runtime_settings.cors_origins,
    allow_origin_regex=runtime_settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router_module in (
    health,
    models,
    generation_preview,
    voices,
    audio,
    tts,
    story,
    speech,
    settings,
    contents,
    websocket,
    voice_conversion,
    files,
):
    app.include_router(router_module.router)
