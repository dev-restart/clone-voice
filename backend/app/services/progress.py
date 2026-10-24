from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from typing import Callable

progress_events: dict[str, dict] = {}
_listeners: dict[str, set[Callable[[dict], None]]] = {}
_lock = RLock()


@contextmanager
def observe_progress(progress_id: str, callback: Callable[[dict], None]):
    """Observe only an owned job; listeners never determine generation success."""
    with _lock:
        _listeners.setdefault(progress_id, set()).add(callback)
    try:
        yield
    finally:
        with _lock:
            callbacks = _listeners.get(progress_id)
            if callbacks is not None:
                callbacks.discard(callback)
                if not callbacks:
                    _listeners.pop(progress_id, None)


def publish_progress(progress_id: str | None, percent: int, message: str, done: bool = False) -> None:
    if not progress_id:
        return
    payload = {"percent": percent, "message": message, "done": done, "timestamp": datetime.now().isoformat()}
    with _lock:
        progress_events[progress_id] = payload
        # Bounded retention for disconnected preview clients as well as jobs.
        if len(progress_events) > 256:
            for old_id in list(progress_events):
                if old_id not in _listeners:
                    progress_events.pop(old_id, None)
                    break
        callbacks = tuple(_listeners.get(progress_id, ()))
    for callback in callbacks:
        try:
            callback(payload.copy())
        except Exception:
            # A status observer must not turn successful inference into failure.
            continue
