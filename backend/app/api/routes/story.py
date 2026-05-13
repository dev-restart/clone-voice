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

@router.post("/api/story-studio/generate", response_model=StoryStudioGenerateResponse)
async def generate_story_studio_audio(
    request: StoryStudioGenerateRequest,
    settings: Settings = Depends(get_settings),
    voice_store: VoiceStore = Depends(get_voice_store),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(request.progress_id, 3, "스토리 단락과 목소리 설정을 확인하고 있습니다.")
    segment_results: list[StorySegmentResult] = []
    generated_parts: list[tuple[Path, int]] = []

    try:
        for index, segment in enumerate(request.segments, start=1):
            voice = voice_store.get(segment.voice_id) if segment.voice_id else None
            if segment.voice_id and voice is None:
                raise HTTPException(status_code=404, detail=f"Voice profile was not found for segment {index}")
            adapter = ensure_adapter_available(router, segment.model_id or request.default_model_id, "tts")
            if not adapter.status().capabilities.tts:
                raise CapabilityUnsupportedError(f"{adapter.label} does not support text-to-speech.")

            progress = 8 + int(index / max(len(request.segments), 1) * 76)
            publish_progress(
                request.progress_id,
                progress,
                f"스토리 단락 {index}/{len(request.segments)} 음성을 생성하고 있습니다.",
            )
            effective_instruct = tts_control_instruct_for_model(
                adapter.model_id,
                tone_prompt=segment.tone_prompt,
                language=segment.language,
                accent=segment.accent,
                speed=segment.speed,
            )
            output = await asyncio.to_thread(
                adapter.generate,
                text=segment.text,
                voice=voice_with_reference_transcript(voice),
                instruct=effective_instruct,
                language=segment.language,
                speed=segment.speed,
                duration=None,
                num_step=request.num_step,
                guidance_scale=request.guidance_scale,
                denoise=request.denoise,
            )
            output_path, duration = output.path, output.duration_seconds
            ensure_generated_audio(output_path, duration)
            generated_parts.append((output_path, segment.pause_after_ms))
            segment_results.append(
                StorySegmentResult(
                    id=segment.id or uuid4().hex,
                    index=index,
                    text=segment.text,
                    language=segment.language,
                    voice_id=voice.id if voice else None,
                    voice_name=voice.name if voice else ("Voice Design" if segment.tone_prompt else "Auto Voice"),
                    model_id=adapter.model_id,
                    audio_url=public_file_url(output_path, "outputs"),
                    duration_seconds=duration,
                    pause_after_ms=segment.pause_after_ms,
                    tone_prompt=segment.tone_prompt,
                    effective_instruct=effective_instruct,
                )
            )

        publish_progress(request.progress_id, 90, "단락 오디오를 하나의 스토리북으로 합치고 있습니다.")
        combined_path, combined_duration = combine_generated_segments(generated_parts, settings.outputs_dir)
        if request.normalize_output:
            combined_path, combined_duration = apply_output_effects(
                combined_path,
                settings.outputs_dir,
                normalize_output=True,
            )
        ensure_generated_audio(combined_path, combined_duration)
    except HTTPException:
        raise
    except CapabilityUnsupportedError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        publish_progress(request.progress_id, 100, f"Story generation failed: {exc}", done=True)
        raise HTTPException(status_code=503, detail=f"Story generation failed: {exc}") from exc

    publish_progress(request.progress_id, 100, "스토리북 오디오 생성이 완료되었습니다.", done=True)
    return StoryStudioGenerateResponse(
        title=request.title.strip() or "새 스토리북",
        audio_url=public_file_url(combined_path, "outputs"),
        duration_seconds=combined_duration,
        segments=segment_results,
    )
