from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import get_router, get_voice_store
from app.config import Settings, get_settings
from app.db.models import DbConversionJob
from app.db.session import session_scope
from app.i18n import tr
from app.schemas import (
    VoiceConversionJobItem,
    VoiceConversionResponse,
    public_file_url,
)
from app.services.audio_effects import apply_output_effects
from app.services.audio_utils import normalize_music_cover_audio
from app.services.generation_helpers import (
    ensure_generated_audio,
)
from app.services.model_helpers import ensure_adapter_available
from app.services.model_router import CapabilityUnsupportedError, ModelRouter, ModelUnavailableError
from app.services.progress import publish_progress
from app.services.voice_store import VoiceStore

import asyncio

router = APIRouter()


def _public_source_audio_url(path_value: str, settings: Settings) -> str | None:
    path = Path(path_value).resolve()
    if path.parent != settings.uploads_dir.resolve():
        return None
    return public_file_url(path, "uploads")

@router.post("/api/voice-conversion", response_model=VoiceConversionResponse)
async def voice_conversion(
    voice_id: str | None = Form(default=None),
    model_id: str | None = Form(default=None),
    language: str | None = Form(default=None),
    progress_id: str | None = Form(default=None),
    trim_start: float | None = Form(default=None),
    trim_end: float | None = Form(default=None),
    conversion_mode: str = Form(default="singing"),
    steps: int = Form(default=4),
    cfg_scale: float = Form(default=2.0),
    auto_shift: bool = Form(default=True),
    pitch_shift: int = Form(default=0),
    separate_vocals: bool = Form(default=True),
    mix_accompaniment: bool = Form(default=True),
    seed: int = Form(default=42),
    volume_gain_db: float = Form(default=0.0),
    normalize_output: bool = Form(default=True),
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(progress_id, 3, tr("원곡과 대상 목소리를 확인하고 있습니다.", "Checking the song and target voice…"))
    if conversion_mode != "singing":
        publish_progress(progress_id, 100, tr("SoulX-Singer는 노래 AI 커버만 지원합니다.", "SoulX-Singer only supports singing AI covers."), done=True)
        raise HTTPException(status_code=422, detail="SoulX-Singer supports singing conversion only")
    if not 1 <= steps <= 32:
        publish_progress(progress_id, 100, tr("생성 단계는 1~32 범위여야 합니다.", "Generation steps must be between 1 and 32."), done=True)
        raise HTTPException(status_code=422, detail="steps must be between 1 and 32")
    if not 0.5 <= cfg_scale <= 4.0:
        publish_progress(progress_id, 100, tr("음색 강도는 0.5~4.0 범위여야 합니다.", "Timbre strength must be between 0.5 and 4.0."), done=True)
        raise HTTPException(status_code=422, detail="cfg_scale must be between 0.5 and 4.0")
    if not -24 <= pitch_shift <= 24:
        publish_progress(progress_id, 100, tr("반음 이동 값은 -24~24 범위여야 합니다.", "Pitch shift must be between -24 and 24 semitones."), done=True)
        raise HTTPException(status_code=422, detail="pitch_shift must be between -24 and 24")
    voice = store.get(voice_id) if voice_id else None
    if voice_id and voice is None:
        publish_progress(progress_id, 100, tr("대상 목소리를 찾지 못했습니다.", "The target voice was not found."), done=True)
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    extension = Path(audio.filename or "source.webm").suffix or ".webm"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    input_path = settings.uploads_dir / f"{uuid4().hex}{extension}"
    content = await audio.read()
    if not content:
        publish_progress(progress_id, 100, tr("원본 음성이 비어 있습니다.", "The source audio is empty."), done=True)
        raise HTTPException(status_code=422, detail="Source audio is required")
    input_path.write_bytes(content)
    selected_duration = (trim_end - trim_start) if trim_start is not None and trim_end is not None else None
    if selected_duration is not None:
        if selected_duration <= 0.3:
            publish_progress(progress_id, 100, tr("선택 구간이 너무 짧습니다. 보컬이 있는 구간을 선택해 주세요.", "The selection is too short. Choose a part with vocals."), done=True)
            raise HTTPException(status_code=422, detail=tr("선택 구간이 너무 짧습니다. 보컬이 있는 구간을 선택해 주세요.", "The selection is too short. Choose a part with vocals."))
    conversion_input = input_path
    publish_progress(progress_id, 8, tr("선택한 원곡 구간을 준비하고 있습니다.", "Preparing the selected part of the song…"))
    normalized_path = settings.uploads_dir / f"{uuid4().hex}-cover-source.wav"
    try:
        normalize_music_cover_audio(input_path, normalized_path, trim_start=trim_start, trim_end=trim_end)
    except RuntimeError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conversion_input = normalized_path
    try:
        adapter = ensure_adapter_available(router, model_id, "voice_conversion")
        if not adapter.status().capabilities.singing_voice_conversion:
            raise CapabilityUnsupportedError(f"{adapter.label} does not support singing voice conversion.")
        publish_progress(progress_id, 16, tr(f"{adapter.label} 보컬 분리와 AI 커버 생성을 시작합니다.", f"Starting vocal separation and AI cover generation with {adapter.label}…"))
        task = asyncio.create_task(
            asyncio.to_thread(
                adapter.convert_voice,
                conversion_input,
                voice,
                language=language,
                duration=selected_duration,
                conversion_mode=conversion_mode,
                steps=steps,
                cfg_scale=cfg_scale,
                auto_shift=auto_shift,
                pitch_shift=pitch_shift,
                separate_vocals=separate_vocals,
                mix_accompaniment=mix_accompaniment,
                seed=seed,
            )
        )
        heartbeat = 0
        while not task.done():
            publish_progress(progress_id, min(86, 20 + heartbeat * 2), tr(f"{adapter.label} AI 커버 처리 중입니다. 경과 {heartbeat}s", f"{adapter.label} is processing the AI cover… {heartbeat}s elapsed"))
            await asyncio.sleep(1)
            heartbeat += 1
        output = await task
        output_path, duration = output.path, output.duration_seconds
        publish_progress(progress_id, 90, tr("변환 음성 후처리와 저장을 진행합니다.", "Post-processing and saving the converted audio…"))
        if volume_gain_db or normalize_output:
            output_path, duration = apply_output_effects(
                output_path,
                settings.outputs_dir,
                pitch_shift=0,
                volume_gain_db=volume_gain_db,
                normalize_output=normalize_output,
            )
        if duration is not None and duration < 0.5:
            raise RuntimeError(tr("생성된 AI 커버가 너무 짧습니다. 보컬이 또렷한 구간을 선택해 다시 변환해 주세요.", "The generated AI cover is too short. Choose a part with clear vocals and convert again."))
        ensure_generated_audio(output_path, duration)
    except CapabilityUnsupportedError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        publish_progress(progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        publish_progress(progress_id, 100, tr(f"AI 커버 생성 실패: {exc}", f"AI cover generation failed: {exc}"), done=True)
        raise HTTPException(status_code=503, detail=tr(f"AI 커버 생성 실패: {exc}", f"AI cover generation failed: {exc}")) from exc
    job_id = uuid4().hex
    job_created_at = None
    with session_scope(settings) as session:
        job = DbConversionJob(
            id=job_id,
            model_id=adapter.model_id,
            source_audio_path=str(input_path),
            target_voice_id=voice.id if voice else None,
            output_audio_url=public_file_url(output_path, "outputs"),
            transcript=output.transcript,
        )
        session.add(job)
        session.flush()
        job_created_at = job.created_at
    publish_progress(progress_id, 100, tr("AI 커버 생성이 완료되었습니다.", "The AI cover is ready."), done=True)
    return VoiceConversionResponse(
        text=output.transcript or "",
        transcript=output.transcript,
        voice_id=voice.id if voice else None,
        audio_url=public_file_url(output_path, "outputs"),
        duration_seconds=duration,
        model_id=adapter.model_id,
        conversion_mode=conversion_mode,
        conversion_options={
            "steps": steps,
            "cfg_scale": cfg_scale,
            "auto_shift": auto_shift,
            "pitch_shift": pitch_shift,
            "separate_vocals": separate_vocals,
            "mix_accompaniment": mix_accompaniment,
            "seed": seed,
        },
        job_id=job_id,
        created_at=job_created_at,
    )


@router.get("/api/voice-conversion/jobs", response_model=list[VoiceConversionJobItem])
def list_voice_conversion_jobs(settings: Settings = Depends(get_settings)):
    with session_scope(settings) as session:
        rows = session.scalars(
            select(DbConversionJob)
            .order_by(DbConversionJob.created_at.desc())
            .limit(50)
        ).all()
        return [
            VoiceConversionJobItem(
                id=row.id,
                model_id=row.model_id,
                source_audio_url=_public_source_audio_url(row.source_audio_path, settings),
                target_voice_id=row.target_voice_id,
                output_audio_url=row.output_audio_url,
                transcript=row.transcript,
                created_at=row.created_at,
            )
            for row in rows
        ]
