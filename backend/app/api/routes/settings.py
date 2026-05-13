from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select

from app.api.deps import get_content_store, get_router, get_voice_store
from app.config import Settings, get_settings
from app.db.models import DbConversionJob, DbSttJob
from app.db.session import session_scope
from app.schemas import (
    ContentCreateRequest,
    ContentGenerateRequest,
    ContentItem,
    ContentResult,
    ContentUpdateRequest,
    GenerateRequest,
    GenerateResponse,
    GenerationPreviewRequest,
    GenerationPreviewResponse,
    HealthResponse,
    ModelListResponse,
    ResultSaveVoiceRequest,
    SmokeTestRequest,
    SmokeTestResponse,
    StorySegmentResult,
    StoryStudioGenerateRequest,
    StoryStudioGenerateResponse,
    SpeechToSpeechResponse,
    STTResponse,
    TranslateRequest,
    TranslateResponse,
    TranscriptSegmentsResponse,
    TTSRequest,
    UploadedAudioResponse,
    VoiceConversionJobItem,
    VoiceConversionResponse,
    VoiceProfile,
    VoiceUpdateRequest,
    YouTubeImportRequest,
    YouTubeImportResponse,
    public_file_url,
)
from app.services.audio_effects import apply_output_effects
from app.services.audio_utils import normalize_reference_audio, normalize_stt_audio, normalize_voice_conversion_audio
from app.services.content_store import ContentStore
from app.services.generation_helpers import (
    build_generation_preview,
    combine_generated_segments,
    ensure_generated_audio,
    narration_instruct,
    parse_narration_script,
    public_audio_url,
    requested_or_estimated_duration,
    run_generation_with_progress,
    transcribe_with_segments,
    voice_with_reference_transcript,
)
from app.services.model_helpers import ensure_adapter_available
from app.services.model_router import CapabilityUnsupportedError, ModelRouter, ModelUnavailableError
from app.services.omnivoice_service import (
    MockVoiceEngine,
    OmniVoiceEngine,
    combine_omnivoice_instruct,
    effective_accent_for_language,
    get_voice_engine,
    language_code_to_omnivoice_language,
)
from app.services.progress import publish_progress
from app.services.stt_service import STTProvider
from app.services.translation_service import OpenAICompatibleTranslator
from app.services.voice_store import VoiceStore
from app.services.youtube_import_service import import_youtube_audio

router = APIRouter()

@router.post("/api/translate", response_model=TranslateResponse)
def translate_text(request: TranslateRequest, settings: Settings = Depends(get_settings)):
    try:
        result = OpenAICompatibleTranslator(settings).translate(request.text, request.languages)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Translation failed: {exc}") from exc
    return TranslateResponse(source_text=request.text, translations=result.translations, provider=result.provider, model=result.model)


@router.get("/api/settings")
def get_runtime_settings(settings: Settings = Depends(get_settings), engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine), router: ModelRouter = Depends(get_router)):
    return {
        "voice_model": engine.status().model_dump(mode="json"),
        "models": [model.model_dump(mode="json") for model in router.list()],
        "default_tts_model": settings.default_tts_model,
        "default_vc_model": settings.default_vc_model,
        "translation": {"base_url": settings.llm_base_url, "model": settings.llm_model},
    }


@router.post("/api/settings/test-voice", response_model=SmokeTestResponse)
def test_voice_settings(
    request: SmokeTestRequest,
    engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine),
):
    try:
        output_path, duration = engine.generate(text=request.text, speed=1.0, num_step=16)
        ensure_generated_audio(output_path, duration)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Voice test failed: {exc}") from exc
    return SmokeTestResponse(ok=True, detail="Voice test succeeded.", audio_url=public_file_url(output_path, "outputs"))


@router.post("/api/settings/test-translation", response_model=SmokeTestResponse)
def test_translation_settings(request: SmokeTestRequest, settings: Settings = Depends(get_settings)):
    try:
        result = OpenAICompatibleTranslator(settings).translate(request.text, request.languages)
        return SmokeTestResponse(ok=True, detail="Translation test succeeded.", translations=result.translations)
    except Exception as exc:
        return SmokeTestResponse(ok=False, detail=f"Translation test failed: {exc}", translations={})
