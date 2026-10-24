"""Thread-safe, coalescing invalidations for one process-local generation queue.

No database reads, payload history or inference run here. Each slow subscriber
retains at most one wake-up; the receiver always reloads the authoritative state.
"""
from __future__ import annotations

import asyncio
from threading import RLock


class GenerationSubscription:
    def __init__(self, hub: "GenerationEvents"):
        self.hub = hub
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self.closed = False
        self.scheduled = False

    def signal(self) -> None:
        with self.hub.lock:
            if self.closed or self.scheduled:
                return
            self.scheduled = True
            try:
                self.loop.call_soon_threadsafe(self._deliver)
            except RuntimeError:
                self.close()

    def _deliver(self) -> None:
        with self.hub.lock:
            self.scheduled = False
            if not self.closed and self.queue.empty():
                self.queue.put_nowait(None)

    async def wait(self) -> None:
        await self.queue.get()

    def close(self) -> None:
        with self.hub.lock:
            self.closed = True
            self.hub.subscribers.discard(self)


class GenerationEvents:
    def __init__(self):
        self.lock = RLock()
        self.subscribers: set[GenerationSubscription] = set()

    def subscribe(self) -> GenerationSubscription:
        with self.lock:
            if len(self.subscribers) >= 32:
                raise RuntimeError("음성 작업 연결이 너무 많습니다. 사용하지 않는 탭을 닫아 주세요.")
            subscription = GenerationSubscription(self)
            self.subscribers.add(subscription)
            return subscription

    def notify(self) -> None:
        with self.lock:
            for subscription in tuple(self.subscribers):
                subscription.signal()
