"""One TTS inference at a time across queued and immediate TTS requests."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from threading import Lock
from app.services.progress import publish_progress

_tts_lock = Lock()


@asynccontextmanager
async def tts_slot(progress_id: str | None = None):
    announced = False
    while not _tts_lock.acquire(blocking=False):
        if not announced:
            publish_progress(progress_id, 1, "앞선 음성 생성을 기다리고 있습니다.")
            announced = True
        await asyncio.sleep(0.1)
    try:
        yield
    finally:
        _tts_lock.release()


@contextmanager
def synchronous_tts_slot():
    with _tts_lock:
        yield


def serialized_tts(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with tts_slot():
            return await function(*args, **kwargs)
    return wrapped
