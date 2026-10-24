import math
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_voice_store
from app.config import Settings, get_settings
from app.db.models import DbSttJob
from app.db.session import session_scope
from app.schemas import (
    STTResponse,
    TranscriptSegmentsResponse,
    UploadedAudioResponse,
    MediaImportRequest,
    MediaImportResponse,
    MediaInfoRequest,
    MediaInfoResponse,
    public_file_url,
)
from app.services.audio_utils import normalize_reference_audio, normalize_stt_audio
from app.services.generation_helpers import (
    public_audio_url,
)
from app.services.stt_service import STTProvider
from app.services.audio_sample_analysis import (
    SampleAnalysisRequest, SampleTranscriptRequest, analyze_sample,
    decode_analysis_audio, resolve_uploaded_audio,
)
from app.services.voice_store import VoiceStore

router = APIRouter()


def get_main_transcriber():
    from app import main as main_module

    return main_module.transcribe_with_segments


def get_media_importer():
    from app import main as main_module

    return main_module.import_media_audio


@router.post("/api/audio/sample-analysis")
def analyze_voice_sample(request: SampleAnalysisRequest, settings: Settings = Depends(get_settings)):
    try:
        return analyze_sample(request.audio_url, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/audio/sample-transcript", response_model=TranscriptSegmentsResponse)
def transcribe_sample_window(request: SampleTranscriptRequest, settings: Settings = Depends(get_settings)):
    if request.end <= request.start or request.end - request.start > 30.01:
        raise HTTPException(status_code=422, detail="주변 받아쓰기는 한 번에 30초 이하로 선택해 주세요.")
    try:
        source = resolve_uploaded_audio(request.audio_url, settings)
        runtime = settings.storage_dir.resolve() / "runtime" / "sample-transcripts"
        runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="window-", dir=runtime) as directory:
            normalized = Path(directory) / "window.wav"
            decoded_seconds = decode_analysis_audio(source, normalized, start=request.start, end=request.end)
            actual_end = request.start + decoded_seconds
            if request.end > actual_end + .25:
                raise ValueError("받아쓰기 구간이 오디오 길이를 벗어났습니다.")
            result = get_main_transcriber()(
                normalized, offset_seconds=request.start, provider=request.provider,
                language=request.language, settings=settings,
            )
            # Keep only finite, meaningful timestamps within the requested source window.
            for segment in result.segments:
                if not (math.isfinite(segment.start) and math.isfinite(segment.end)
                        and request.start <= segment.start < actual_end
                        and segment.start < segment.end <= actual_end + .25):
                    raise RuntimeError("받아쓰기의 시간 정보가 선택한 오디오 범위와 맞지 않습니다.")
                segment.end = min(segment.end, actual_end)
            return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
        filename=audio.filename or destination.name,
    )


def get_media_inspector():
    from app import main as main_module

    return main_module.inspect_media


@router.post("/api/audio/media-info", response_model=MediaInfoResponse)
def inspect_media_endpoint(
    request: MediaInfoRequest,
    settings: Settings = Depends(get_settings),
):
    try:
        info = get_media_inspector()(request.url, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MediaInfoResponse(
        platform=info.platform,
        title=info.title,
        webpage_url=info.webpage_url,
        duration_seconds=info.duration_seconds,
        uploader=info.uploader,
        max_duration_seconds=info.max_duration_seconds,
    )


@router.post("/api/audio/media-import", response_model=MediaImportResponse)
def import_media_audio_endpoint(
    request: MediaImportRequest,
    settings: Settings = Depends(get_settings),
):
    try:
        # The clip range is only forwarded when asked for, so importers without range support keep working.
        clip = {key: value for key, value in (("start_seconds", request.start_seconds), ("end_seconds", request.end_seconds)) if value is not None}
        imported = get_media_importer()(request.url, settings, isolate_voice=request.isolate_voice, **clip)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MediaImportResponse(
        platform=imported.platform,
        title=imported.title,
        webpage_url=imported.webpage_url,
        duration_seconds=imported.duration_seconds,
        audio_url=public_file_url(imported.audio_path, "uploads"),
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
