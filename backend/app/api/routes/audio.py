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


def get_main_transcriber():
    from app import main as main_module

    return main_module.transcribe_with_segments


def get_youtube_importer():
    from app import main as main_module

    return main_module.import_youtube_audio


@router.post("/api/audio/transcript-segments", response_model=TranscriptSegmentsResponse)
async def transcribe_uploaded_segments(
    audio: UploadFile = File(...),
    provider: STTProvider = Form(default="whisper"),
    language: str | None = Form(default=None),
    trim_start: float | None = Form(default=None),
    trim_end: float | None = Form(default=None),
    settings: Settings = Depends(get_settings),
):
    extension = Path(audio.filename or "audio.webm").suffix or ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.uploads_dir / f"{uuid4().hex}{extension}"
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is required")
    if trim_start is not None and trim_end is not None and trim_end <= trim_start:
        raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")
    input_path.write_bytes(content)
    transcribe_path = input_path
    offset = trim_start or 0
    if trim_start is not None or trim_end is not None:
        transcribe_path = settings.uploads_dir / f"{uuid4().hex}.wav"
        try:
            normalize_reference_audio(input_path, transcribe_path, trim_start=trim_start, trim_end=trim_end)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return get_main_transcriber()(transcribe_path, offset_seconds=offset, provider=provider, language=language, settings=settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/audio/uploads", response_model=UploadedAudioResponse)
async def upload_audio_source(
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    extension = Path(audio.filename or "audio.webm").suffix.lower() or ".webm"
    if extension not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"}:
        extension = ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.uploads_dir / f"{uuid4().hex}{extension}"
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is required")
    destination.write_bytes(content)
    return UploadedAudioResponse(
        audio_url=public_file_url(destination, "uploads"),
        audio_path=str(destination),
        filename=audio.filename or destination.name,
    )


@router.post("/api/audio/youtube-import", response_model=YouTubeImportResponse)
def import_youtube_audio_endpoint(
    request: YouTubeImportRequest,
    settings: Settings = Depends(get_settings),
):
    try:
        imported = get_youtube_importer()(request.url, settings, isolate_voice=request.isolate_voice)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return YouTubeImportResponse(
        title=imported.title,
        webpage_url=imported.webpage_url,
        duration_seconds=imported.duration_seconds,
        audio_url=public_file_url(imported.audio_path, "uploads"),
        audio_path=str(imported.audio_path),
        filename=imported.audio_path.name,
        voice_isolated=imported.voice_isolated,
    )


@router.post("/api/stt", response_model=STTResponse)
async def speech_to_text(
    audio: UploadFile = File(...),
    provider: STTProvider = Form(default="whisper"),
    language: str | None = Form(default=None),
    trim_start: float | None = Form(default=None),
    trim_end: float | None = Form(default=None),
    settings: Settings = Depends(get_settings),
):
    extension = Path(audio.filename or "speech.webm").suffix or ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.uploads_dir / f"{uuid4().hex}{extension}"
    normalized_path = settings.uploads_dir / f"{uuid4().hex}-stt.wav"
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is required")
    if trim_start is not None and trim_end is not None and trim_end <= trim_start:
        raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")
    input_path.write_bytes(content)
    try:
        normalize_stt_audio(input_path, normalized_path, trim_start=trim_start, trim_end=trim_end)
        transcript = get_main_transcriber()(normalized_path, offset_seconds=trim_start or 0, provider=provider, language=language, settings=settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    job_id = uuid4().hex
    with session_scope(settings) as session:
        session.add(
            DbSttJob(
                id=job_id,
                source_audio_path=str(input_path),
                normalized_audio_path=str(normalized_path),
                language=language,
                text=transcript.text,
                provider=provider,
            )
        )
    return STTResponse(
        id=job_id,
        text=transcript.text,
        segments=transcript.segments,
        language=language,
        audio_url=public_audio_url(input_path, settings, "uploads"),
        provider=provider,
        model=settings.whisper_model if provider == "whisper" else "Apple Speech Framework",
    )


@router.get("/api/voices/{voice_id}/transcript-segments", response_model=TranscriptSegmentsResponse)
def transcribe_voice_segments(
    voice_id: str,
    provider: STTProvider = "whisper",
    language: str | None = None,
    trim_start: float | None = None,
    trim_end: float | None = None,
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
):
    voice = store.get(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    if trim_start is not None and trim_end is not None and trim_end <= trim_start:
        raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")
    source_path = Path(voice.source_audio_path or voice.audio_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Original audio file was not found")
    transcribe_path = source_path
    offset = trim_start or 0
    if trim_start is not None or trim_end is not None:
        transcribe_path = settings.uploads_dir / f"{uuid4().hex}.wav"
        try:
            normalize_reference_audio(source_path, transcribe_path, trim_start=trim_start, trim_end=trim_end)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return get_main_transcriber()(transcribe_path, offset_seconds=offset, provider=provider, language=language, settings=settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
