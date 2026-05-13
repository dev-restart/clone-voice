from datetime import datetime
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

@router.get("/api/voices", response_model=list[VoiceProfile])
def list_voices(settings: Settings = Depends(get_settings), store: VoiceStore = Depends(get_voice_store)):
    voices = store.list()
    for voice in voices:
        if voice.source_audio_path:
            voice.source_audio_url = public_audio_url(Path(voice.source_audio_path), settings)
    return voices


@router.post("/api/voices", response_model=VoiceProfile, status_code=201)
async def create_voice(
    name: str = Form(...),
    transcript: str | None = Form(default=None),
    trim_start: float | None = Form(default=None),
    trim_end: float | None = Form(default=None),
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
):
    cleaned_name = name.strip() or f"샘플 목소리 {datetime.now().strftime('%H:%M')}"
    extension = Path(audio.filename or "voice.wav").suffix or ".wav"
    raw_filename = f"{uuid4().hex}{extension}"
    wav_filename = f"{uuid4().hex}.wav"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    raw_path = settings.uploads_dir / raw_filename
    destination = settings.voices_dir / wav_filename
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is required")
    if trim_start is not None and trim_end is not None and trim_end <= trim_start:
        raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")
    raw_path.write_bytes(content)
    try:
        normalize_reference_audio(raw_path, destination, trim_start=trim_start, trim_end=trim_end)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    voice = VoiceProfile(
        name=cleaned_name,
        transcript=transcript.strip() if transcript and transcript.strip() else None,
        audio_path=str(destination),
        audio_url=public_file_url(destination, "voices"),
        source_audio_path=str(raw_path),
        source_audio_url=public_audio_url(raw_path, settings),
        trim_start=trim_start,
        trim_end=trim_end,
    )
    return store.save(voice)


@router.get("/api/voices/{voice_id}", response_model=VoiceProfile)
def get_voice(voice_id: str, settings: Settings = Depends(get_settings), store: VoiceStore = Depends(get_voice_store)):
    voice = store.get(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    if voice.source_audio_path:
        voice.source_audio_url = public_audio_url(Path(voice.source_audio_path), settings)
    return voice


@router.patch("/api/voices/{voice_id}", response_model=VoiceProfile)
def update_voice(voice_id: str, request: VoiceUpdateRequest, settings: Settings = Depends(get_settings), store: VoiceStore = Depends(get_voice_store)):
    voice = store.get(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    if request.name is not None:
        voice.name = request.name.strip() or voice.name
    if request.description is not None:
        voice.description = request.description.strip() or None
    if request.avatar is not None:
        voice.avatar = request.avatar.strip() or None
    if request.transcript is not None:
        voice.transcript = request.transcript.strip() or None
    trim_requested = request.trim_start is not None or request.trim_end is not None
    if trim_requested:
        trim_start_value = request.trim_start if request.trim_start is not None else 0
        trim_end_value = request.trim_end if request.trim_end is not None else None
        if trim_end_value is not None and trim_end_value <= trim_start_value:
            raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")
        source_path = Path(voice.source_audio_path or voice.audio_path)
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Original audio file was not found")
        destination = Path(voice.audio_path)
        try:
            normalize_reference_audio(source_path, destination, trim_start=trim_start_value, trim_end=trim_end_value)
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        voice.trim_start = trim_start_value
        voice.trim_end = trim_end_value
        voice.audio_url = public_file_url(destination, "voices")
        voice.source_audio_url = public_audio_url(source_path, settings)
    return store.save(voice)


@router.post("/api/voices/{voice_id}/avatar", response_model=VoiceProfile)
async def upload_voice_avatar(
    voice_id: str,
    avatar: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
):
    voice = store.get(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    if avatar.content_type and not avatar.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="Avatar image file is required")
    content = await avatar.read()
    if not content:
        raise HTTPException(status_code=422, detail="Avatar image file is required")
    extension = Path(avatar.filename or "avatar.png").suffix.lower() or ".png"
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        extension = ".png"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.uploads_dir / f"{voice_id}-avatar-{uuid4().hex}{extension}"
    destination.write_bytes(content)
    voice.avatar = public_file_url(destination, "uploads")
    return store.save(voice)


@router.delete("/api/voices/{voice_id}", status_code=204)
def delete_voice(voice_id: str, store: VoiceStore = Depends(get_voice_store)):
    voice = store.delete(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    try:
        Path(voice.audio_path).unlink(missing_ok=True)
        if voice.source_audio_path and voice.source_audio_path != voice.audio_path:
            Path(voice.source_audio_path).unlink(missing_ok=True)
    except OSError:
        pass
    return Response(status_code=204)
