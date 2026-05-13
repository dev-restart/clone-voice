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
    split_plain_tts_text,
    tts_control_instruct_for_model,
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

@router.post("/api/generate", response_model=GenerateResponse)
def generate_voice(
    request: GenerateRequest,
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
    engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine),
    router: ModelRouter = Depends(get_router),
):
    voice = None
    if request.voice_id:
        voice = store.get(request.voice_id)
        if voice is None:
            raise HTTPException(status_code=404, detail="Voice profile was not found")
    try:
        resolved_model_id = getattr(engine, "engine_name", None)
        if request.model_id:
            adapter = ensure_adapter_available(router, request.model_id, "tts")
            if not adapter.status().capabilities.tts:
                raise CapabilityUnsupportedError(f"{adapter.label} does not support text-to-speech.")
            output = adapter.generate(
                text=request.text,
                voice=voice_with_reference_transcript(voice),
                instruct=tts_control_instruct_for_model(
                    adapter.model_id,
                    tone_prompt=request.tone_prompt,
                    instruct=request.instruct,
                    style_prompt=request.style_prompt,
                    language=request.language,
                    accent=request.accent,
                    speed=request.speed,
                ),
                language=request.language,
                speed=request.speed,
                duration=requested_or_estimated_duration(request.duration, request.text, request.speed),
                num_step=request.num_step,
                guidance_scale=request.guidance_scale,
                denoise=request.denoise,
                position_temperature=request.position_temperature,
                class_temperature=request.class_temperature,
                preprocess_prompt=request.preprocess_prompt,
                postprocess_output=request.postprocess_output,
                audio_chunk_duration=request.audio_chunk_duration,
                audio_chunk_threshold=request.audio_chunk_threshold,
            )
            output_path, duration = output.path, output.duration_seconds
            resolved_model_id = adapter.model_id
        else:
            output_path, duration = engine.generate(
                text=request.text,
                voice=voice_with_reference_transcript(voice),
                instruct=combine_omnivoice_instruct(request.instruct, request.language, request.accent),
                language=request.language,
                speed=request.speed,
                duration=requested_or_estimated_duration(request.duration, request.text, request.speed),
                num_step=request.num_step,
                guidance_scale=request.guidance_scale,
                denoise=request.denoise,
                position_temperature=request.position_temperature,
                class_temperature=request.class_temperature,
                preprocess_prompt=request.preprocess_prompt,
                postprocess_output=request.postprocess_output,
                audio_chunk_duration=request.audio_chunk_duration,
                audio_chunk_threshold=request.audio_chunk_threshold,
            )
        if request.pitch_shift or request.volume_gain_db or request.normalize_output:
            output_path, duration = apply_output_effects(
                output_path,
                settings.outputs_dir,
                pitch_shift=request.pitch_shift,
                volume_gain_db=request.volume_gain_db,
                normalize_output=request.normalize_output,
            )
        ensure_generated_audio(output_path, duration)
    except CapabilityUnsupportedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Voice generation failed: {exc}") from exc
    return GenerateResponse(
        text=request.text,
        voice_id=request.voice_id,
        audio_url=public_file_url(output_path, "outputs"),
        duration_seconds=duration,
        model_id=resolved_model_id,
    )


@router.post("/api/tts", response_model=GenerateResponse)
async def generate_tts(
    request: TTSRequest,
    settings: Settings = Depends(get_settings),
    store: VoiceStore = Depends(get_voice_store),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(request.progress_id, 3, "요청 내용을 확인하고 있습니다.")
    voice = None
    if request.voice_id:
        voice = store.get(request.voice_id)
        if voice is None:
            publish_progress(request.progress_id, 100, "목소리 정보를 찾지 못했습니다.", done=True)
            raise HTTPException(status_code=404, detail="Voice profile was not found")
    try:
        adapter = ensure_adapter_available(router, request.model_id, "tts")
        if not adapter.status().capabilities.tts:
            raise CapabilityUnsupportedError(f"{adapter.label} does not support text-to-speech.")
        publish_progress(request.progress_id, 12, f"{adapter.label} 모델에 음성 생성을 요청했습니다.")
        narration_segments = parse_narration_script(request.text)
        auto_chunked = False
        if not narration_segments:
            narration_segments = split_plain_tts_text(request.text, model_id=adapter.model_id, language=request.language, speed=request.speed)
            auto_chunked = bool(narration_segments)
        base_instruct = tts_control_instruct_for_model(
            adapter.model_id,
            tone_prompt=request.tone_prompt,
            instruct=request.instruct,
            style_prompt=request.style_prompt,
            language=request.language,
            accent=request.accent,
            speed=request.speed,
        )
        if narration_segments:
            generated_parts = []
            for index, segment in enumerate(narration_segments, start=1):
                segment_label = "긴 본문 조각" if auto_chunked else "연출 문장"
                chunk_start = 12 + int(((index - 1) / max(len(narration_segments), 1)) * 70)
                chunk_end = 12 + int((index / max(len(narration_segments), 1)) * 70)
                if adapter.model_id == "voxcpm":
                    if auto_chunked:
                        segment_instruct = base_instruct
                    else:
                        segment_prompt = ", ".join(
                            item
                            for item in (
                                str(segment.get("tone") or "").strip(),
                                str(segment.get("pitch") or "").strip(),
                                request.tone_prompt or "",
                            )
                            if item
                        )
                        segment_instruct = tts_control_instruct_for_model(
                            adapter.model_id,
                            tone_prompt=segment_prompt or None,
                            instruct=request.instruct,
                            style_prompt=request.style_prompt,
                            language=request.language,
                            accent=request.accent,
                            speed=segment["speed"] or request.speed,
                        )
                else:
                    segment_instruct = narration_instruct(segment, request.tone_prompt or request.instruct, request.language, request.accent)
                task = asyncio.create_task(
                    asyncio.to_thread(
                        adapter.generate,
                        text=segment["text"],
                        voice=voice_with_reference_transcript(voice),
                        instruct=segment_instruct,
                        language=request.language,
                        speed=segment["speed"] or request.speed,
                        duration=None,
                        num_step=request.num_step,
                        guidance_scale=request.guidance_scale,
                        denoise=request.denoise,
                        position_temperature=request.position_temperature,
                        class_temperature=request.class_temperature,
                        preprocess_prompt=request.preprocess_prompt,
                        postprocess_output=request.postprocess_output,
                        audio_chunk_duration=request.audio_chunk_duration,
                        audio_chunk_threshold=request.audio_chunk_threshold,
                    )
                )
                heartbeat = 0
                while not task.done():
                    publish_progress(
                        request.progress_id,
                        max(chunk_start, min(86, chunk_end - 1, chunk_start + 1 + heartbeat // 5)),
                        f"{adapter.label} {segment_label} {index}/{len(narration_segments)} 생성 중입니다. 경과 {heartbeat}s",
                    )
                    await asyncio.sleep(1)
                    heartbeat += 1
                output = await task
                generated_parts.append((output.path, segment["pause_after_ms"]))
            output_path, duration = combine_generated_segments(generated_parts, settings.outputs_dir)
        else:
            task = asyncio.create_task(
                asyncio.to_thread(
                    adapter.generate,
                    text=request.text,
                    voice=voice_with_reference_transcript(voice),
                    instruct=base_instruct,
                    language=request.language,
                    speed=request.speed,
                    duration=requested_or_estimated_duration(request.duration, request.text, request.speed),
                    num_step=request.num_step,
                    guidance_scale=request.guidance_scale,
                    denoise=request.denoise,
                    position_temperature=request.position_temperature,
                    class_temperature=request.class_temperature,
                    preprocess_prompt=request.preprocess_prompt,
                    postprocess_output=request.postprocess_output,
                    audio_chunk_duration=request.audio_chunk_duration,
                    audio_chunk_threshold=request.audio_chunk_threshold,
                )
            )
            heartbeat = 0
            while not task.done():
                publish_progress(
                    request.progress_id,
                    min(86, 18 + heartbeat * 4),
                    f"{adapter.label} 음성 생성 중입니다. 경과 {heartbeat}s",
                )
                await asyncio.sleep(1)
                heartbeat += 1
            output = await task
            output_path, duration = output.path, output.duration_seconds
        publish_progress(request.progress_id, 90, "음량 정규화와 결과 파일 저장을 진행합니다.")
        if request.pitch_shift or request.volume_gain_db or request.normalize_output:
            output_path, duration = apply_output_effects(
                output_path,
                settings.outputs_dir,
                pitch_shift=request.pitch_shift,
                volume_gain_db=request.volume_gain_db,
                normalize_output=request.normalize_output,
            )
        ensure_generated_audio(output_path, duration)
    except CapabilityUnsupportedError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        publish_progress(request.progress_id, 100, f"TTS generation failed: {exc}", done=True)
        raise HTTPException(status_code=503, detail=f"TTS generation failed: {exc}") from exc
    publish_progress(request.progress_id, 100, "음성 생성이 완료되었습니다.", done=True)
    return GenerateResponse(
        text=request.text,
        voice_id=request.voice_id,
        audio_url=public_file_url(output_path, "outputs"),
        duration_seconds=duration,
        model_id=adapter.model_id,
    )
