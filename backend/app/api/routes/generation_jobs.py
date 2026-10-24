"""Persistent TTS jobs; submitted scripts stay independent from editable drafts."""
import asyncio
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from anyio import CancelScope
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_content_store, get_router, get_voice_store
from app.api.routes.contents import generate_content_snapshot
from app.config import Settings, get_settings
from app.i18n import tr
from app.schemas import ContentGenerateRequest, ContentItem, ContentProductionSettings, VoiceProfile
from app.services.content_store import ContentStore
from app.services.generation_queue import GenerationQueue, QueueError
from app.services.model_helpers import ensure_adapter_available
from app.services.model_router import ModelRouter, CapabilityUnsupportedError, ModelUnavailableError
from app.services.omnivoice_service import get_voice_engine
from app.services.voice_store import VoiceStore

router = APIRouter()
Language = Literal["ko", "en", "ja", "zh", "es", "fr", "de"]


class ContentJobsRequest(ContentGenerateRequest):
    batch_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    languages: list[Language] = Field(min_length=1, max_length=7)
    text_overrides: dict[Language, str] = Field(default_factory=dict)
    production_settings: ContentProductionSettings | None = None

    @field_validator("text_overrides")
    @classmethod
    def bounded_texts(cls, value):
        if any(not text.strip() or len(text) > 60000 for text in value.values()):
            raise ValueError(tr("다시 만들 대본은 1~60,000자여야 합니다.", "The script to regenerate must be 1–60,000 characters."))
        return value


class RetryRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


def queue_for(settings: Settings) -> GenerationQueue:
    store = ContentStore(settings.contents_dir, settings)
    def recovered(job):
        content = store.get(job["content_id"])
        expected = f'{job["id"]}-{job["language"]}'
        return [result.id for result in content.results if result.id == expected] if content else []
    return GenerationQueue(settings, recover_result_ids=recovered)


def runner_for(settings: Settings, model_router: ModelRouter):
    def run(job):
        try:
            store = ContentStore(settings.contents_dir, settings)
            current = store.get(job["content_id"])
            if current is None:
                raise RuntimeError(tr("대본이 삭제되어 음성을 만들지 않았습니다.", "The script was deleted, so no speech was generated."))
            snapshot = job["snapshot"]
            voice = VoiceProfile.model_validate(snapshot["voice"]) if snapshot.get("voice") else None
            if voice is not None and VoiceStore(settings.voices_dir, settings).get(voice.id) is None:
                raise RuntimeError(tr("등록 목소리가 삭제되었습니다. 사용할 목소리를 다시 선택해 주세요.", "The registered voice was deleted. Choose a voice again."))
            production = ContentProductionSettings.model_validate(snapshot["production_settings"])
            item = ContentItem(
                id=current.id, title=current.title, source_language=job["language"],
                source_text=snapshot["text"], production_settings=production,
                created_at=current.created_at,
            )
            request = ContentGenerateRequest.model_validate(snapshot["request"])
            request = request.model_copy(update={"languages": [job["language"]], "progress_id": job["id"]})
            saved = asyncio.run(generate_content_snapshot(
                item, request, settings=settings, content_store=store,
                voice=voice, engine=get_voice_engine(settings), router=model_router,
                result_id_prefix=job["id"],
            ))
            expected = f'{job["id"]}-{job["language"]}'
            return [result.id for result in saved.results if result.id == expected]
        except HTTPException as exc:
            raise RuntimeError(str(exc.detail)) from exc
    return run


@router.post("/api/contents/{content_id}/jobs", status_code=202)
def enqueue_content_jobs(
    content_id: str, request: ContentJobsRequest,
    settings: Settings = Depends(get_settings),
    content_store: ContentStore = Depends(get_content_store),
    voice_store: VoiceStore = Depends(get_voice_store),
    model_router: ModelRouter = Depends(get_router),
):
    content = content_store.get(content_id)
    if content is None:
        raise HTTPException(status_code=404, detail=tr("대본을 찾을 수 없습니다.", "The script was not found."))
    voice = voice_store.get(request.voice_id) if request.voice_id else None
    if request.voice_id and voice is None:
        raise HTTPException(status_code=404, detail=tr("등록 목소리를 찾을 수 없습니다.", "The registered voice was not found."))
    if request.model_id:
        try:
            ensure_adapter_available(model_router, request.model_id, "tts")
        except (CapabilityUnsupportedError, ModelUnavailableError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    production = request.production_settings or content.production_settings or ContentProductionSettings(language=content.source_language)
    snapshots = []
    for language in dict.fromkeys(request.languages):
        text = request.text_overrides.get(language, content.source_text if language == content.source_language else content.translations.get(language, ""))
        if not text.strip() or len(text) > 60000:
            raise HTTPException(status_code=422, detail=tr(f"{language} 대본은 1~60,000자여야 합니다. 저장된 대본을 확인해 주세요.", f"The {language} script must be 1–60,000 characters. Check the saved script."))
        snapshots.append({
            "language": language, "text": text,
            "production_settings": production.model_dump(mode="json"),
            "request": request.model_dump(mode="json", exclude={"batch_id", "text_overrides", "languages", "progress_id", "production_settings"}),
            "voice": voice.model_dump(mode="json") if voice else None,
        })
    try:
        jobs = queue_for(settings).enqueue(request.batch_id, content_id, snapshots, runner_for(settings, model_router))
    except QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"jobs": jobs, "concurrency": 1}


@router.websocket("/api/ws/generation-jobs")
async def generation_job_events(websocket: WebSocket, settings: Settings = Depends(get_settings)):
    # Unlike CORS, WebSocket origin checks must be explicit before acceptance.
    origin = websocket.headers.get("origin")
    try:
        parsed = urlsplit(origin) if origin else None
        valid_origin = parsed is None or (parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and not parsed.username and not parsed.password)
    except ValueError:
        valid_origin = False
    if not valid_origin:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    subscription = None
    tasks = []
    try:
        queue = await run_in_threadpool(queue_for, settings)
        # Subscribe before the initial snapshot so no commit can fall in a gap.
        subscription = queue.events.subscribe()

        async def send_updates():
            sequence = 0
            while True:
                jobs = await run_in_threadpool(queue.list)
                sequence += 1
                await asyncio.wait_for(websocket.send_json({"type": "snapshot", "sequence": sequence, "jobs": jobs, "concurrency": 1}), timeout=10)
                while True:
                    try:
                        await asyncio.wait_for(subscription.wait(), timeout=20)
                        # Coalesce fast model progress without a periodic DB poll.
                        await asyncio.sleep(0.15)
                        break
                    except asyncio.TimeoutError:
                        await asyncio.wait_for(websocket.send_json({"type": "heartbeat"}), timeout=10)

        async def receive_control():
            last_resync = 0.0
            while True:
                message = await websocket.receive_text()
                if message != "resync":
                    await websocket.close(code=1008)
                    return
                now = asyncio.get_running_loop().time()
                if now - last_resync >= 1.0:
                    subscription.signal()
                    last_resync = now

        tasks = [asyncio.create_task(send_updates()), asyncio.create_task(receive_control())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, asyncio.TimeoutError, asyncio.CancelledError):
        pass
    except Exception:
        # Do not expose model configuration, source scripts or server tracebacks.
        try:
            await websocket.close(code=1011, reason=tr("음성 작업 상태 연결을 다시 확인하세요.", "Check the speech job status connection again."))
        except (RuntimeError, OSError):
            pass
    finally:
        if subscription is not None:
            subscription.close()
        for task in tasks:
            task.cancel()
        if tasks:
            # ASGI shutdown/disconnect may cancel the enclosing AnyIO scope.
            # Drain only our socket tasks, never the backend generation worker.
            with CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)


@router.get("/api/generation-jobs")
def list_generation_jobs(content_id: str | None = Query(default=None, max_length=80), settings: Settings = Depends(get_settings)):
    try:
        return {"jobs": queue_for(settings).list(content_id), "concurrency": 1}
    except QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/generation-jobs/{job_id}/cancel")
def cancel_generation_job(job_id: str, settings: Settings = Depends(get_settings)):
    try:
        return queue_for(settings).cancel(job_id)
    except QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/api/generation-jobs/{job_id}/retry", status_code=202)
def retry_generation_job(job_id: str, request: RetryRequest, settings: Settings = Depends(get_settings), model_router: ModelRouter = Depends(get_router)):
    try:
        return queue_for(settings).retry(job_id, request.batch_id, runner_for(settings, model_router))
    except QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
