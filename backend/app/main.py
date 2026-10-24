from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.services.generation_queue import close_generation_queues
from fastapi.middleware.cors import CORSMiddleware

from app.i18n import LocaleMiddleware

from app.api.routes import (
    ai_profiles,
    assets,
    audio,
    contents,
    content_exports,
    files,
    generation_preview,
    generation_jobs,
    health,
    models,
    production_assist,
    script_assist,
    settings,
    sound_effects,
    sound_projects,
    studio_preferences,
    speech,
    story,
    story_projects,
    tts,
    voice_conversion,
    voices,
    websocket,
)
# 외부에서 dependency와 media importer를 교체할 수 있도록 app module에도 공개합니다.
from app.api.deps import get_router  # noqa: F401
from app.config import get_settings
from app.services.generation_helpers import transcribe_with_segments  # noqa: F401
from app.services.media_import_service import import_media_audio, inspect_media  # noqa: F401

runtime_settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_generation_queues(wait=False)


app = FastAPI(
    lifespan=lifespan,
    title=runtime_settings.app_name,
    version="0.1.0",
    summary="Local-first AI voice production API",
    description=(
        "Backend API for Clone Voice Studio. It manages voice profiles, TTS generation, "
        "speech transcription, YouTube and Instagram media import, dialogue audio, voice conversion, generated files, and model health."
    ),
)
app.add_middleware(LocaleMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=runtime_settings.cors_origins,
    allow_origin_regex=runtime_settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router_module in (
    ai_profiles,
    health,
    models,
    generation_preview,
    assets,
    voices,
    audio,
    tts,
    production_assist,
    script_assist,
    story,
    story_projects,
    speech,
    settings,
    sound_effects,
    sound_projects,
    studio_preferences,
    generation_jobs,
    contents,
    content_exports,
    websocket,
    voice_conversion,
    files,
):
    app.include_router(router_module.router)