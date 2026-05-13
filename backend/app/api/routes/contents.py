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
from shutil import copyfile

router = APIRouter()

@router.get("/api/contents", response_model=list[ContentItem])
def list_contents(store: ContentStore = Depends(get_content_store)):
    return store.list()


@router.post("/api/contents", response_model=ContentItem, status_code=201)
def create_content(request: ContentCreateRequest, store: ContentStore = Depends(get_content_store)):
    item = ContentItem(title=request.title.strip() or "새 음성 콘텐츠", source_text=request.source_text.strip(), translations=request.translations)
    if not item.source_text:
        raise HTTPException(status_code=422, detail="Source text is required")
    return store.save(item)


@router.patch("/api/contents/{content_id}", response_model=ContentItem)
def update_content(content_id: str, request: ContentUpdateRequest, store: ContentStore = Depends(get_content_store)):
    item = store.get(content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content was not found")
    if request.title is not None:
        item.title = request.title.strip() or item.title
    if request.source_text is not None:
        item.source_text = request.source_text.strip()
    if request.translations is not None:
        item.translations = request.translations
    return store.save(item)


@router.delete("/api/contents/{content_id}", status_code=204)
def delete_content(content_id: str, store: ContentStore = Depends(get_content_store)):
    item = store.delete(content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content was not found")
    return Response(status_code=204)


@router.post("/api/contents/{content_id}/generate", response_model=ContentItem)
async def generate_content_audio(
    content_id: str,
    request: ContentGenerateRequest,
    settings: Settings = Depends(get_settings),
    content_store: ContentStore = Depends(get_content_store),
    voice_store: VoiceStore = Depends(get_voice_store),
    engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine),
    router: ModelRouter = Depends(get_router),
):
    publish_progress(request.progress_id, 5, "콘텐츠와 목소리 정보를 확인하고 있습니다.")
    item = content_store.get(content_id)
    if item is None:
        publish_progress(request.progress_id, 100, "콘텐츠를 찾지 못했습니다.", done=True)
        raise HTTPException(status_code=404, detail="Content was not found")
    voice = voice_store.get(request.voice_id) if request.voice_id else None
    if request.voice_id and voice is None:
        publish_progress(request.progress_id, 100, "목소리 정보를 찾지 못했습니다.", done=True)
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    targets = []
    for language in request.languages:
        text = item.source_text if language == "ko" else item.translations.get(language, "")
        if text.strip():
            targets.append((language, text))
    if not targets:
        publish_progress(request.progress_id, 100, "선택한 언어에 사용할 대본이 없습니다.", done=True)
        raise HTTPException(status_code=422, detail="No script text was available for the selected languages")
    adapter = None
    if request.model_id:
        try:
            adapter = ensure_adapter_available(router, request.model_id, "tts")
            if not adapter.status().capabilities.tts:
                raise CapabilityUnsupportedError(f"{adapter.label} does not support text-to-speech.")
        except CapabilityUnsupportedError as exc:
            publish_progress(request.progress_id, 100, str(exc), done=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ModelUnavailableError as exc:
            publish_progress(request.progress_id, 100, str(exc), done=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    for index, (language, text) in enumerate(targets, start=1):
        base_percent = 12 + int(((index - 1) / len(targets)) * 76)
        next_percent = 12 + int((index / len(targets)) * 76)
        language_hint = language_code_to_omnivoice_language(language)
        prompt_model_id = adapter.model_id if adapter else "omnivoice"
        effective_instruct = tts_control_instruct_for_model(
            prompt_model_id,
            tone_prompt=request.tone_prompt,
            style_prompt=request.style_prompt,
            language=language,
            accent=request.accent,
            speed=request.speed,
        )
        accent_hint = effective_accent_for_language(language, request.accent)
        publish_progress(request.progress_id, base_percent, f"{language} 합성 요청을 모델에 전달했습니다. ({index}/{len(targets)})")
        try:
            if adapter:
                auto_segments = split_plain_tts_text(text, model_id=adapter.model_id, language=language, speed=request.speed)
                if auto_segments:
                    generated_parts = []
                    total_segments = len(auto_segments)
                    progress_span = max(1, next_percent - base_percent)
                    for segment_index, segment in enumerate(auto_segments, start=1):
                        chunk_start = base_percent + int(((segment_index - 1) / total_segments) * progress_span)
                        chunk_end = base_percent + int((segment_index / total_segments) * progress_span)
                        chunk_end = max(chunk_start + 1, chunk_end)
                        task = asyncio.create_task(
                            asyncio.to_thread(
                                adapter.generate,
                                text=segment["text"],
                                voice=voice_with_reference_transcript(voice),
                                instruct=effective_instruct,
                                language=language_code_to_omnivoice_language(language) or language,
                                speed=request.speed,
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
                                max(chunk_start, min(next_percent - 1, chunk_end - 1, chunk_start + 1 + heartbeat // 5)),
                                f"{adapter.label} {language} 긴 본문 조각 {segment_index}/{total_segments} 생성 중입니다. 경과 {heartbeat}s",
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
                            text=text,
                            voice=voice_with_reference_transcript(voice),
                            instruct=effective_instruct,
                            language=language_code_to_omnivoice_language(language) or language,
                            speed=request.speed,
                            duration=requested_or_estimated_duration(request.duration, text, request.speed),
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
                            min(next_percent - 1, base_percent + 8 + heartbeat * 4),
                            f"{adapter.label} {language} 음성 생성 중입니다. 경과 {heartbeat}s",
                        )
                        await asyncio.sleep(1)
                        heartbeat += 1
                    output = await task
                    output_path, duration = output.path, output.duration_seconds
            else:
                output_path, duration = await run_generation_with_progress(
                    progress_id=request.progress_id,
                    engine=engine,
                    text=text,
                    voice=voice,
                    tone_prompt=request.tone_prompt,
                    language_code=language,
                    accent=request.accent,
                    speed=request.speed,
                    duration=requested_or_estimated_duration(request.duration, text, request.speed),
                    num_step=request.num_step,
                    guidance_scale=request.guidance_scale,
                    denoise=request.denoise,
                    position_temperature=request.position_temperature,
                    class_temperature=request.class_temperature,
                    preprocess_prompt=request.preprocess_prompt,
                    postprocess_output=request.postprocess_output,
                    audio_chunk_duration=request.audio_chunk_duration,
                    audio_chunk_threshold=request.audio_chunk_threshold,
                    start_percent=base_percent,
                    end_percent=next_percent,
                    label=language,
                )
            publish_progress(request.progress_id, min(next_percent, 90), f"{language} 음성 후처리와 저장을 진행합니다.")
            if request.pitch_shift or request.volume_gain_db or request.normalize_output:
                output_path, duration = apply_output_effects(
                    output_path,
                    settings.outputs_dir,
                    pitch_shift=request.pitch_shift,
                    volume_gain_db=request.volume_gain_db,
                    normalize_output=request.normalize_output,
                )
            ensure_generated_audio(output_path, duration)
        except Exception as exc:
            publish_progress(request.progress_id, base_percent, f"{language} 생성 실패: {exc}", done=True)
            raise HTTPException(status_code=503, detail=f"Content generation failed for {language}: {exc}") from exc
        item.results.insert(
            0,
            ContentResult(
                language=language,
                text=text,
                voice_id=voice.id if voice else None,
                voice_name=voice.name if voice else ("Voice Design" if request.tone_prompt else "Auto Voice"),
                model_id=adapter.model_id if adapter else getattr(engine, "engine_name", None),
                audio_url=public_file_url(output_path, "outputs"),
                duration_seconds=duration,
                tone_prompt=request.tone_prompt,
                style_prompt=request.style_prompt,
                effective_instruct=effective_instruct,
                language_hint=language_hint,
                accent_hint=accent_hint,
            )
        )
    saved = content_store.save(item)
    publish_progress(request.progress_id, 100, "모든 언어의 음성 생성과 저장이 완료되었습니다.", done=True)
    return saved


@router.post("/api/contents/{content_id}/results/{result_id}/save-voice", response_model=VoiceProfile, status_code=201)
def save_content_result_as_voice(
    content_id: str,
    result_id: str,
    request: ResultSaveVoiceRequest,
    settings: Settings = Depends(get_settings),
    content_store: ContentStore = Depends(get_content_store),
    voice_store: VoiceStore = Depends(get_voice_store),
):
    item = content_store.get(content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content was not found")
    result = next((entry for entry in item.results if entry.id == result_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail="Generated result was not found")
    if request.trim_start is not None and request.trim_end is not None and request.trim_end <= request.trim_start:
        raise HTTPException(status_code=422, detail="Trim end must be greater than trim start")

    output_filename = Path(result.audio_url).name
    output_path = (settings.outputs_dir / output_filename).resolve()
    if not output_path.exists() or output_path.parent != settings.outputs_dir.resolve():
        raise HTTPException(status_code=404, detail="Generated audio file was not found")

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.voices_dir.mkdir(parents=True, exist_ok=True)
    source_path = settings.uploads_dir / f"{uuid4().hex}{output_path.suffix or '.wav'}"
    destination = settings.voices_dir / f"{uuid4().hex}.wav"
    try:
        copyfile(output_path, source_path)
        normalize_reference_audio(source_path, destination, trim_start=request.trim_start, trim_end=request.trim_end)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not save generated audio as a voice: {exc}") from exc

    language_label = result.language.upper()
    default_name = f"{result.voice_name or 'Generated Voice'} · {language_label}"
    voice = VoiceProfile(
        name=(request.name.strip() if request.name and request.name.strip() else default_name),
        transcript=(request.transcript.strip() if request.transcript and request.transcript.strip() else result.text),
        audio_path=str(destination),
        audio_url=public_file_url(destination, "voices"),
        source_audio_path=str(source_path),
        source_audio_url=public_audio_url(source_path, settings),
        trim_start=request.trim_start,
        trim_end=request.trim_end,
    )
    return voice_store.save(voice)


@router.delete("/api/contents/{content_id}/results/{result_id}", response_model=ContentItem)
def delete_content_result(
    content_id: str,
    result_id: str,
    settings: Settings = Depends(get_settings),
    content_store: ContentStore = Depends(get_content_store),
):
    item = content_store.get(content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content was not found")
    result_to_delete = next((result for result in item.results if result.id == result_id), None)
    if result_to_delete is None:
        raise HTTPException(status_code=404, detail="Generated result was not found")
    item.results = [result for result in item.results if result.id != result_id]
    saved = content_store.save(item)
    output_filename = Path(result_to_delete.audio_url).name
    output_path = (settings.outputs_dir / output_filename).resolve()
    if output_path.parent == settings.outputs_dir.resolve() and output_path.exists():
        output_path.unlink(missing_ok=True)
    return saved
