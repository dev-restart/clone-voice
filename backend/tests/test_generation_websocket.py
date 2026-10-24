"""Real queue + WebSocket tests; synthetic runners never load speech models."""
import asyncio
import json
import time
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings, get_settings
from app.api.routes.generation_jobs import router, queue_for
from app.services.generation_events import GenerationEvents
from app.services.progress import publish_progress


def snapshot():
    return {'language': 'ko', 'text': 'PRIVATE_SOURCE_MUST_NOT_STREAM', 'request': {}, 'production_settings': {}}


@pytest.fixture
def environment(tmp_path):
    settings = Settings(_env_file=None, storage_dir=tmp_path)
    queue = queue_for(settings)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield queue, client
    queue.close(wait=True)


def read_until(ws, predicate):
    for _ in range(15):
        payload = ws.receive_json()
        if predicate(payload):
            return payload
    pytest.fail('Expected queue event was not delivered')


def test_event_hub_coalesces_cross_thread_signals_and_unsubscribes():
    async def scenario():
        hub = GenerationEvents()
        subscription = hub.subscribe()
        await asyncio.to_thread(lambda: [hub.notify() for _ in range(500)])
        await asyncio.wait_for(subscription.wait(), 1)
        assert subscription.queue.qsize() <= 1
        subscription.close()
        assert not hub.subscribers
        hub.notify()
    asyncio.run(scenario())


def test_idle_socket_does_not_poll_storage_and_rejects_external_origin(environment, monkeypatch):
    queue, client = environment
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/ws/generation-jobs', headers={'origin': 'https://untrusted.example'}):
            pass
    calls = []
    original = queue.list
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(queue, 'list', counted)
    with client.websocket_connect('/api/ws/generation-jobs', headers={'origin': 'http://127.0.0.1:5190'}) as ws:
        assert ws.receive_json()['jobs'] == []
        time.sleep(.4)
        assert len(calls) == 1
        ws.send_text('resync')
        assert ws.receive_json()['type'] == 'snapshot'
        assert len(calls) == 2
    assert not queue.events.subscribers


def test_progress_survives_disconnect_and_completed_state_reconnects(environment):
    queue, client = environment
    started, release = Event(), Event()
    invocations = []
    def runner(job):
        invocations.append(job['id'])
        publish_progress(job['id'], 42, '합성 중')
        started.set()
        assert release.wait(5)
        return [job['id'] + '-ko']
    try:
        with client.websocket_connect('/api/ws/generation-jobs') as ws:
            assert ws.receive_json()['jobs'] == []
            job = queue.enqueue('ws-batch', 'content-ws', [snapshot()], runner)[0]
            assert started.wait(2)
            progress = read_until(ws, lambda p: any(j.get('progress', {}).get('percent') == 42 for j in p.get('jobs', [])))
            assert 'PRIVATE_SOURCE_MUST_NOT_STREAM' not in json.dumps(progress)
            assert 'snapshot' not in progress['jobs'][0]
        assert not queue.events.subscribers
        release.set()
        # No HTTP or WebSocket polling is needed for the worker to finish.
        deadline = time.monotonic() + 3
        while queue._futures and time.monotonic() < deadline:
            time.sleep(.01)
        assert queue._store.get(job['id'])['status'] == 'completed'
        with client.websocket_connect('/api/ws/generation-jobs') as ws:
            recovered = ws.receive_json()
            assert recovered['jobs'][0]['status'] == 'completed'
            ws.send_text('resync')
            assert ws.receive_json()['jobs'][0]['status'] == 'completed'
        assert invocations == [job['id']]
    finally:
        release.set()


def test_completion_commit_repairs_without_any_browser(environment, monkeypatch):
    queue, _ = environment
    queue._completion_retry_delay = .05
    save = queue._store.save_many
    failed = [False]
    calls = []
    def flaky(jobs):
        if not failed[0] and any(j['status'] == 'completed' for j in jobs):
            failed[0] = True
            raise OSError('synthetic first commit failure')
        save(jobs)
    monkeypatch.setattr(queue._store, 'save_many', flaky)
    def runner(job):
        calls.append(job['id'])
        return [job['id'] + '-ko']
    job = queue.enqueue('persist-once', 'content-ws', [snapshot()], runner)[0]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        # Direct durable reads intentionally do not trigger list()/get() repair.
        if queue._store.get(job['id'])['status'] == 'completed':
            break
        time.sleep(.02)
    assert queue._store.get(job['id'])['status'] == 'completed'
    assert failed[0] and calls == [job['id']]


def test_two_websocket_observers_share_one_generation(environment):
    queue, client = environment
    calls = []
    with client.websocket_connect('/api/ws/generation-jobs') as first, client.websocket_connect('/api/ws/generation-jobs') as second:
        first.receive_json(); second.receive_json()
        def runner(job):
            calls.append(job['id'])
            return [job['id'] + '-ko']
        job = queue.enqueue('two-observers', 'content-ws', [snapshot()], runner)[0]
        for ws in (first, second):
            result = read_until(ws, lambda p: any(j['status'] == 'completed' for j in p.get('jobs', [])))
            assert result['jobs'][0]['id'] == job['id']
        assert calls == [job['id']]
    assert not queue.events.subscribers
