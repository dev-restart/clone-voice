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

import asyncio

router = APIRouter()

@router.post("/api/voice-conversion", response_model=VoiceConversionResponse)
async def voice_conversion(
    voice_id: str | None = Form(default=None),
    model_id: str | None = Form(default=None),
    language: str | None = Form(default=None),
    progress_id: str | None = Form(default=None),
    trim_start: float | None = Form(default=None),
    trim_end: float | None = Form(default=None),
    speed: float = Form(default=1.0),
    num_step: int = Form(default=32),
    conversion_mode: str = Form(default="voice"),
    diffusion_steps: int | None = Form(default=None),
    length_adjust: float | None = Form(default=None),
    inference_cfg_rate: float | None = Form(default=None),
    f0_condition: bool | None = Form(default=None),
    auto_f0_adjust: bool | None = Form(default=None),
    semi_tone_shift: int | None = Form(default=None),
    fp16: bool | None = Form(default=None),
    checkpoint: str | None = Form(default=None),
    config: str | None = Form(default=None),
    intelligibility_cfg_rate: float | None = Form(default=None),
    similarity_cfg_rate: float | None = Form(default=None),
    top_p: float | None = Form(default=None),
    temperature: float | None = Form(default=None),
    repetition_penalty: float | None = Form(default=None),
    convert_style: bool = Form(default=False),
    anonymization_only: bool = Form(default=False),
    ar_checkpoint_path: str | None = Form(default=None),
    cfm_checkpoint_path: str | None = Form(default=None),
    pitch_shift: float = Form(default=0.0),
    volume_gain_db: float = Form(default=0.0),
    normalize_output: bool = Form(default=True),
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(progress_id, 3, "원본 음성과 대상 목소리를 확인하고 있습니다.")
    if conversion_mode not in {"voice", "singing", "v2"}:
        publish_progress(progress_id, 100, "지원하지 않는 Seed-VC 변환 모드입니다.", done=True)
        raise HTTPException(status_code=422, detail="Unsupported Seed-VC conversion mode")
    if diffusion_steps is not None and not 4 <= diffusion_steps <= 120:
        publish_progress(progress_id, 100, "Diffusion step 값은 4~120 범위여야 합니다.", done=True)
        raise HTTPException(status_code=422, detail="diffusion_steps must be between 4 and 120")
    if length_adjust is not None and not 0.5 <= length_adjust <= 2.0:
        publish_progress(progress_id, 100, "Length adjust 값은 0.5~2.0 범위여야 합니다.", done=True)
        raise HTTPException(status_code=422, detail="length_adjust must be between 0.5 and 2.0")
    if semi_tone_shift is not None and not -24 <= semi_tone_shift <= 24:
        publish_progress(progress_id, 100, "반음 이동 값은 -24~24 범위여야 합니다.", done=True)
        raise HTTPException(status_code=422, detail="semi_tone_shift must be between -24 and 24")
    voice = store.get(voice_id) if voice_id else None
    if voice_id and voice is None:
        publish_progress(progress_id, 100, "대상 목소리를 찾지 못했습니다.", done=True)
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    extension = Path(audio.filename or "source.webm").suffix or ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.uploads_dir / f"{uuid4().hex}{extension}"
    content = await audio.read()
    if not content:
        publish_progress(progress_id, 100, "원본 음성이 비어 있습니다.", done=True)
        raise HTTPException(status_code=422, detail="Source audio is required")
    input_path.write_bytes(content)
    selected_duration = (trim_end - trim_start) if trim_start is not None and trim_end is not None else None
    if selected_duration is not None:
        if selected_duration <= 0.3:
            publish_progress(progress_id, 100, "선택 구간이 너무 짧습니다. 말소리가 있는 구간을 선택해 주세요.", done=True)
            raise HTTPException(status_code=422, detail="선택 구간이 너무 짧습니다. 말소리가 있는 구간을 선택해 주세요.")
    conversion_input = input_path
    publish_progress(progress_id, 8, "선택 구간을 보이스 체인저용 WAV로 정규화하고 있습니다.")
    normalized_path = settings.uploads_dir / f"{uuid4().hex}-vc-source.wav"
    try:
        normalize_voice_conversion_audio(input_path, normalized_path, trim_start=trim_start, trim_end=trim_end)
    except RuntimeError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversion_input = normalized_path
    try:
        adapter = ensure_adapter_available(router, model_id, "voice_conversion")
        if not adapter.status().capabilities.voice_conversion:
            raise CapabilityUnsupportedError(f"{adapter.label} does not support voice conversion.")
        mode_label = "보컬/SVC" if conversion_mode == "singing" else "V2 스타일/익명화" if conversion_mode == "v2" else "음성"
        publish_progress(progress_id, 16, f"Seed-VC {mode_label} 변환을 시작합니다.")
        task = asyncio.create_task(
            asyncio.to_thread(
                adapter.convert_voice,
                conversion_input,
                voice,
                language=language,
                speed=speed,
                num_step=num_step,
                duration=selected_duration,
                conversion_mode=conversion_mode,
                diffusion_steps=diffusion_steps,
                length_adjust=length_adjust,
                inference_cfg_rate=inference_cfg_rate,
                f0_condition=f0_condition,
                auto_f0_adjust=auto_f0_adjust,
                semi_tone_shift=semi_tone_shift,
                fp16=fp16,
                checkpoint=checkpoint,
                config=config,
                intelligibility_cfg_rate=intelligibility_cfg_rate,
                similarity_cfg_rate=similarity_cfg_rate,
                top_p=top_p,
                temperature=temperature,
                repetition_penalty=repetition_penalty,
                convert_style=convert_style,
                anonymization_only=anonymization_only,
                ar_checkpoint_path=ar_checkpoint_path,
                cfm_checkpoint_path=cfm_checkpoint_path,
            )
        )
        heartbeat = 0
        while not task.done():
            publish_progress(progress_id, min(86, 20 + heartbeat * 4), f"{adapter.label} 보이스 체인저 처리 중입니다. 경과 {heartbeat}s")
            await asyncio.sleep(1)
            heartbeat += 1
        output = await task
        output_path, duration = output.path, output.duration_seconds
        publish_progress(progress_id, 90, "변환 음성 후처리와 저장을 진행합니다.")
        if pitch_shift or volume_gain_db or normalize_output:
            output_path, duration = apply_output_effects(
                output_path,
                settings.outputs_dir,
                pitch_shift=pitch_shift,
                volume_gain_db=volume_gain_db,
                normalize_output=normalize_output,
            )
        if duration is not None and duration < 0.5:
            raise RuntimeError("생성된 음성이 너무 짧습니다. 선택 구간을 3~8초로 줄이고, 말소리가 또렷한 구간만 선택해 다시 변환해 주세요.")
        ensure_generated_audio(output_path, duration)
    except CapabilityUnsupportedError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        publish_progress(progress_id, 100, f"Voice conversion failed: {exc}", done=True)
        raise HTTPException(status_code=503, detail=f"Voice conversion failed: {exc}") from exc
    job_id = uuid4().hex
    with session_scope(settings) as session:
        session.add(
            DbConversionJob(
                id=job_id,
                model_id=adapter.model_id,
                source_audio_path=str(input_path),
                target_voice_id=voice.id if voice else None,
                output_audio_url=public_file_url(output_path, "outputs"),
                transcript=output.transcript,
            )
        )
    publish_progress(progress_id, 100, "보이스 체인저 변환이 완료되었습니다.", done=True)
    return VoiceConversionResponse(
        text=output.transcript or "",
        transcript=output.transcript,
        voice_id=voice.id if voice else None,
        audio_url=public_file_url(output_path, "outputs"),
        duration_seconds=duration,
        model_id=adapter.model_id,
        conversion_mode=conversion_mode,
        seed_vc_options={
            "diffusion_steps": diffusion_steps,
            "length_adjust": length_adjust,
            "inference_cfg_rate": inference_cfg_rate,
            "f0_condition": f0_condition,
            "auto_f0_adjust": auto_f0_adjust,
            "semi_tone_shift": semi_tone_shift,
            "fp16": fp16,
            "convert_style": convert_style,
            "anonymization_only": anonymization_only,
        },
    )


@router.get("/api/voice-conversion/jobs", response_model=list[VoiceConversionJobItem])
def list_voice_conversion_jobs(settings: Settings = Depends(get_settings)):
    with session_scope(settings) as session:
        rows = session.scalars(
            select(DbConversionJob)
            .where(DbConversionJob.model_id == settings.default_vc_model)
            .order_by(DbConversionJob.created_at.desc())
            .limit(50)
        ).all()
        return [
            VoiceConversionJobItem(
                id=row.id,
                model_id=row.model_id,
                source_audio_path=row.source_audio_path,
                target_voice_id=row.target_voice_id,
                output_audio_url=row.output_audio_url,
                transcript=row.transcript,
                created_at=row.created_at,
            )
            for row in rows
        ]


@router.get("/api/voice-conversion/realtime/status")
def realtime_voice_conversion_status(router: ModelRouter = Depends(get_router)):
    adapter = router.get("seed-vc", "voice_conversion")
    try:
        return adapter.realtime_status()
    except CapabilityUnsupportedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/voice-conversion/realtime/launch")
def launch_realtime_voice_conversion(
    checkpoint_path: str | None = Form(default=None),
    config_path: str | None = Form(default=None),
    fp16: bool | None = Form(default=None),
    gpu: int = Form(default=0),
    router: ModelRouter = Depends(get_router),
):
    adapter = router.get("seed-vc", "voice_conversion")
    try:
        return adapter.launch_realtime(checkpoint_path=checkpoint_path, config_path=config_path, fp16=fp16, gpu=gpu)
    except CapabilityUnsupportedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Seed-VC real-time launch failed: {exc}") from exc
