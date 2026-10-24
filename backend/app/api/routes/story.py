from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_router, get_voice_store
from app.config import Settings, get_settings
from app.i18n import tr
from app.schemas import (
    DialogueDraftRequest,
    DialogueDraftResponse,
    StorySegmentResult,
    StoryStudioGenerateRequest,
    StoryStudioGenerateResponse,
    public_file_url,
)
from app.services.audio_effects import apply_output_effects, match_speech_level
from app.services.generation_helpers import (
    combine_generated_segments,
    ensure_generated_audio,
    tts_control_instruct_for_model,
    voice_with_reference_transcript,
)
from app.services.dialogue_draft_service import (
    DialogueDraftFormatError,
    DialogueDraftGenerationError,
    generate_dialogue_draft,
)
from app.services.model_helpers import ensure_adapter_available
from app.services.model_router import CapabilityUnsupportedError, ModelRouter, ModelUnavailableError
from app.services.progress import publish_progress
from app.services.voice_store import VoiceStore
from app.services.story_project_store import StoryProjectConflictError, StoryProjectStore

import asyncio

router = APIRouter()


@router.post("/api/story-studio/dialogue-draft", response_model=DialogueDraftResponse)
def create_dialogue_draft(
    request: DialogueDraftRequest,
    settings: Settings = Depends(get_settings),
):
    try:
        return generate_dialogue_draft(request, settings)
    except DialogueDraftFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DialogueDraftGenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/story-studio/generate", response_model=StoryStudioGenerateResponse)
async def generate_story_studio_audio(
    request: StoryStudioGenerateRequest,
    settings: Settings = Depends(get_settings),
    voice_store: VoiceStore = Depends(get_voice_store),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(request.progress_id, 3, tr("대화 단락과 목소리 설정을 확인하고 있습니다.", "Checking the dialogue segments and voices…"))
    segment_results: list[StorySegmentResult] = []
    generated_parts: list[tuple[Path, int]] = []

    try:
        store = StoryProjectStore(settings)
        if request.project_id and store.get(request.project_id) is None:
            raise HTTPException(status_code=404, detail=tr("저장된 대화 프로젝트를 찾지 못했습니다.", "The saved dialogue project was not found."))
        # Check every dependency before starting expensive inference. A bad later
        # segment must not leave a partially generated conversation behind.
        prepared = []
        for index, segment in enumerate(request.segments, start=1):
            if segment.segment_type == "sfx":
                adapter = ensure_adapter_available(router, settings.default_sfx_model, "sound_effect_generation")
                if not adapter.status().capabilities.sound_effect_generation:
                    raise CapabilityUnsupportedError(tr("효과음 생성 모델을 확인하세요.", "Check the sound-effect model."))
                voice = None
            else:
                voice = voice_store.get(segment.voice_id) if segment.voice_id else None
                if segment.voice_id and voice is None:
                    raise HTTPException(status_code=404, detail=tr(f"{index}번 단락의 등록 목소리를 찾지 못했습니다. 다시 지정하세요.", f"The registered voice of segment {index} was not found. Choose it again."))
                adapter = ensure_adapter_available(router, segment.model_id or request.default_model_id, "tts")
                if not adapter.status().capabilities.tts:
                    raise CapabilityUnsupportedError(f"{adapter.label} does not support text-to-speech.")
                if voice and not adapter.status().capabilities.voice_clone_tts:
                    raise CapabilityUnsupportedError(tr(f"{adapter.label} 모델은 등록 목소리 복제를 지원하지 않습니다.", f"{adapter.label} does not support cloning registered voices."))
            prepared.append((adapter, voice))
        for index, segment in enumerate(request.segments, start=1):
            adapter, voice = prepared[index - 1]
            progress = 8 + int(index / max(len(request.segments), 1) * 76)
            if segment.segment_type == "sfx":
                publish_progress(
                    request.progress_id,
                    progress,
                    tr(f"효과음 큐 {index}/{len(request.segments)}를 생성하고 있습니다.", f"Generating sound-effect cue {index}/{len(request.segments)}…"),
                )
                output = await asyncio.to_thread(
                    adapter.generate_sound_effect,
                    prompt=segment.text,
                    negative_prompt="speech, voice, music",
                    duration_seconds=segment.sfx_duration_seconds,
                    steps=8,
                    guidance_scale=3.0,
                    seed=index,
                )
                voice = None
                effective_instruct = None
            else:
                publish_progress(
                    request.progress_id,
                    progress,
                    tr(f"대사 {index}/{len(request.segments)} 음성을 생성하고 있습니다.", f"Generating speech for line {index}/{len(request.segments)}…"),
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
            if segment.segment_type == "speech" and adapter.model_id == "voxcpm" and abs(segment.speed - 1.0) >= 0.01:
                output_path, duration = apply_output_effects(
                    output_path,
                    settings.outputs_dir,
                    playback_speed=segment.speed,
                    normalize_output=False,
                )
            if segment.segment_type == "speech" and request.normalize_output:
                output_path, duration = match_speech_level(output_path, settings.outputs_dir)
            generated_parts.append((output_path, segment.pause_after_ms))
            segment_results.append(
                StorySegmentResult(
                    id=segment.id or uuid4().hex,
                    index=index,
                    text=segment.text,
                    language=segment.language,
                    voice_id=voice.id if voice else None,
                    voice_name=(
                        "효과음"
                        if segment.segment_type == "sfx"
                        else voice.name if voice else (segment.speaker_name or "기본 목소리")
                    ),
                    model_id=adapter.model_id,
                    audio_url=public_file_url(output_path, "outputs"),
                    duration_seconds=duration,
                    segment_type=segment.segment_type,
                    speaker_name=segment.speaker_name,
                    pause_after_ms=segment.pause_after_ms,
                    tone_prompt=segment.tone_prompt,
                    effective_instruct=effective_instruct,
                )
            )

        publish_progress(request.progress_id, 90, tr("단락 오디오를 하나의 대화 오디오로 합치고 있습니다.", "Merging the segment audio into one dialogue…"))
        combined_path, combined_duration = combine_generated_segments(generated_parts, settings.outputs_dir)
        if request.normalize_output:
            combined_path, combined_duration = apply_output_effects(
                combined_path,
                settings.outputs_dir,
                normalize_output=True,
            )
        ensure_generated_audio(combined_path, combined_duration)
        response = StoryStudioGenerateResponse(
            title=request.title.strip() or tr("새 대화 오디오", "New dialogue audio"),
            audio_url=public_file_url(combined_path, "outputs"),
            duration_seconds=combined_duration,
            segments=segment_results,
            source_segments=request.segments,
        )
        if request.project_id:
            store.save_result(request.project_id, response)
    except HTTPException as exc:
        publish_progress(request.progress_id, 100, str(exc.detail), done=True)
        raise
    except StoryProjectConflictError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CapabilityUnsupportedError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ModelUnavailableError as exc:
        publish_progress(request.progress_id, 100, str(exc), done=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        publish_progress(request.progress_id, 100, tr(f"대화 오디오 생성에 실패했습니다: {exc}", f"Dialogue audio generation failed: {exc}"), done=True)
        raise HTTPException(status_code=503, detail=tr(f"대화 오디오 생성에 실패했습니다: {exc}", f"Dialogue audio generation failed: {exc}")) from exc

    publish_progress(request.progress_id, 100, tr("대화 오디오 생성이 완료되었습니다.", "Dialogue audio is ready."), done=True)
    return response
