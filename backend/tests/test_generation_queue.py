"""Regression tests for persisted TTS snapshots, lifecycle, and serialization.

Uses the application's real DbStudioSetting table against an isolated SQLite
database. Inference is controlled with Events; no audio models are loaded.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event, Lock
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import DbStudioSetting
from app.services import generation_queue as module
from app.services.generation_queue import (
    GenerationQueue,
    QueueConflictError,
    QueueNotFoundError,
    QueueValidationError,
)


def snapshot(language: str = "ko", text: str = "저장한 대본입니다.") -> dict:
    return {
        "language": language,
        "text": text,
        "request": {"voice_id": "voice-1", "seed": 7},
        "production_settings": {"speed": 1.0, "nested": {"mode": "normal"}},
    }


def wait_status(queue: GenerationQueue, job_id: str, expected: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = queue.get(job_id)
        if job["status"] == expected:
            return job
        time.sleep(0.01)
    pytest.fail(f"Expected {expected}, got {queue.get(job_id)}")


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'generation-queue.sqlite3'}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    DbStudioSetting.__table__.create(engine)

    @contextmanager
    def sessions(_settings):
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    monkeypatch.setattr(module, "session_scope", sessions)
    settings = SimpleNamespace(resolved_database_url=database_url)
    owned: list[GenerationQueue] = []

    def create():
        queue = GenerationQueue(settings)
        if queue not in owned:
            owned.append(queue)
        return queue

    yield SimpleNamespace(create=create, settings=settings, engine=engine, sessions=sessions)
    for queue in owned:
        queue.close(wait=True)
    engine.dispose()


def test_snapshot_is_private_and_detached_from_caller_and_runner(queue_env):
    queue = queue_env.create()
    started, release = Event(), Event()
    seen: list[dict] = []

    def runner(job):
        started.set()
        assert release.wait(5)
        seen.append(deepcopy(job["snapshot"]))
        job["snapshot"]["text"] = "runner mutation"
        job["snapshot"]["production_settings"]["nested"]["mode"] = "mutated"
        return [{"id": "result-1", "text": "private output metadata"}]

    incoming = snapshot()
    expected = deepcopy(incoming)
    job = queue.enqueue("batch-private", "content-1", [incoming], runner)[0]
    try:
        assert started.wait(5)
        incoming["text"] = "생성 접수 후 바꾼 대본"
        incoming["request"]["voice_id"] = "another-voice"
        incoming["production_settings"]["nested"]["mode"] = "caller mutation"
        assert "snapshot" not in job
        assert "batch_digest" not in job
        assert "request" not in queue.list()[0]
    finally:
        release.set()
    completed = wait_status(queue, job["id"], "completed")
    assert completed["result_ids"] == ["result-1"]
    assert seen == [expected]
    assert queue._store.get(job["id"])["snapshot"] == expected


def test_duplicate_batch_is_idempotent_and_language_order_is_not_identity(queue_env):
    queue = queue_env.create()
    release = Event()
    calls: list[str] = []

    def runner(job):
        assert release.wait(5)
        calls.append(job["language"])
        return ["result-" + job["language"]]

    inputs = [snapshot("en", "Hello"), snapshot("ja", "こんにちは")]
    original = queue.enqueue("batch-idempotent", "content-1", inputs, runner)
    try:
        again = queue.enqueue("batch-idempotent", "content-1", list(reversed(inputs)), runner)
        assert [item["id"] for item in again] == [item["id"] for item in reversed(original)]
        with pytest.raises(QueueConflictError):
            queue.enqueue("batch-idempotent", "content-1", [snapshot("en", "Changed"), inputs[1]], runner)
        with pytest.raises(QueueConflictError):
            queue.enqueue("batch-idempotent", "content-2", inputs, runner)
        with pytest.raises(QueueConflictError):
            queue.enqueue("batch-idempotent", "content-1", [inputs[0]], runner)
        assert len(queue.list()) == 2
    finally:
        release.set()
    for job in original:
        wait_status(queue, job["id"], "completed")
    assert sorted(calls) == ["en", "ja"]


def test_concurrent_duplicate_submissions_share_one_job_and_one_run(queue_env):
    queue = queue_env.create()
    calls: list[str] = []

    def runner(job):
        calls.append(job["id"])
        return ["same-result"]

    with ThreadPoolExecutor(max_workers=4) as callers:
        futures = [callers.submit(queue.enqueue, "same-batch", "content-1", [snapshot()], runner) for _ in range(8)]
        ids = [future.result(timeout=5)[0]["id"] for future in futures]
    assert len(set(ids)) == 1
    wait_status(queue, ids[0], "completed")
    assert calls == [ids[0]]
    assert len(queue.list()) == 1


def test_only_queued_jobs_cancel_and_a_cancelled_job_never_runs(queue_env):
    queue = queue_env.create()
    started, release = Event(), Event()
    calls: list[str] = []

    def runner(job):
        calls.append(job["language"])
        if job["language"] == "ko":
            started.set()
            assert release.wait(5)
        return ["result-" + job["language"]]

    first = queue.enqueue("first", "content-1", [snapshot()], runner)[0]
    try:
        assert started.wait(5)
        second = queue.enqueue("second", "content-1", [snapshot("en", "Hello")], runner)[0]
        with pytest.raises(QueueConflictError):
            queue.cancel(first["id"])
        cancelled = queue.cancel(second["id"])
        assert cancelled["status"] == "cancelled"
        assert queue.cancel(second["id"])["status"] == "cancelled"
    finally:
        release.set()
    wait_status(queue, first["id"], "completed")
    queue.close(wait=True)
    assert calls == ["ko"]
    assert queue.get(second["id"])["status"] == "cancelled"


def test_capacity_is_atomic_and_all_accepted_jobs_use_one_worker(queue_env):
    queue = queue_env.create()
    assert GenerationQueue(queue_env.settings) is queue
    started, release = Event(), Event()
    counter_lock = Lock()
    active = peak = calls = 0

    def runner(job):
        nonlocal active, peak, calls
        with counter_lock:
            active += 1
            calls += 1
            peak = max(peak, active)
        try:
            if job["language"] == "ko":
                started.set()
                assert release.wait(5)
            return ["result-" + job["language"]]
        finally:
            with counter_lock:
                active -= 1

    first = queue.enqueue("occupy", "content-1", [snapshot()], runner)[0]
    try:
        assert started.wait(5)
        rest = queue.enqueue("fill", "content-2", [snapshot(f"lang{i}", "text") for i in range(31)], runner)
        with pytest.raises(QueueConflictError):
            queue.enqueue("overflow", "content-3", [snapshot("fr", "Bonjour")], runner)
        assert len(queue.list()) == 32
        queue.close(wait=False)
    finally:
        release.set()
    queue.close(wait=True)
    # close intentionally prevents starting pending work, so use a fresh batch
    # below for serialization rather than mistaking close for a queue drain.
    assert peak == 1
    assert calls == 1
    assert queue.get(first["id"])["status"] == "completed"
    assert all(queue.get(job["id"])["status"] == "queued" for job in rest)


def test_worker_runs_multiple_batches_serially_until_all_finish(queue_env):
    queue = queue_env.create()
    counter_lock = Lock()
    active = peak = 0
    seen: list[str] = []

    def runner(job):
        nonlocal active, peak
        with counter_lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        seen.append(job["id"])
        with counter_lock:
            active -= 1
        return ["output-" + job["id"]]

    jobs = []
    for index in range(3):
        jobs.extend(queue.enqueue(f"batch-{index}", f"content-{index}", [snapshot("ko"), snapshot("en", "English")], runner))
    for job in jobs:
        wait_status(queue, job["id"], "completed")
    assert peak == 1
    assert seen == [job["id"] for job in jobs]


def test_failed_job_retry_has_new_identity_and_original_snapshot(queue_env):
    queue = queue_env.create()

    def fails(job):
        raise RuntimeError("의도한 생성 실패")

    original = queue.enqueue("failed-batch", "content-1", [snapshot(text="원래 접수한 글")], fails)[0]
    failed = wait_status(queue, original["id"], "failed")
    assert failed["message"] == "의도한 생성 실패"
    seen: list[str] = []

    def succeeds(job):
        seen.append(job["snapshot"]["text"])
        return ["retry-result"]

    retried = queue.retry(original["id"], "retry-batch", succeeds)
    duplicate = queue.retry(original["id"], "retry-batch", succeeds)
    assert duplicate["id"] == retried["id"]
    assert retried["id"] != original["id"]
    assert retried["parent_job_id"] == original["id"]
    wait_status(queue, retried["id"], "completed")
    assert seen == ["원래 접수한 글"]
    assert queue.get(original["id"])["status"] == "failed"
    with pytest.raises(QueueConflictError):
        queue.retry(original["id"], "failed-batch", succeeds)
    with pytest.raises(QueueConflictError):
        queue.retry(retried["id"], "again", succeeds)


def test_startup_fails_unfinished_jobs_without_replaying_and_preserves_history(queue_env):
    queue = queue_env.create()
    completed = queue.enqueue("done", "content-1", [snapshot()], lambda job: ["done-result"])[0]
    wait_status(queue, completed["id"], "completed")
    template = queue._store.get(completed["id"])
    unfinished = []
    for status in ("queued", "running"):
        job = deepcopy(template)
        job.update(id=str(uuid4()), batch_id=f"old-{status}", status=status, result_ids=[])
        unfinished.append(job)
    queue._store.save_many(unfinished)
    queue.close(wait=True)
    reopened = queue_env.create()
    assert reopened is not queue
    for job in unfinished:
        recovered = reopened.get(job["id"])
        assert recovered["status"] == "failed"
        assert "재시작" in recovered["message"]
        assert recovered["result_ids"] == []
    assert reopened.get(completed["id"])["status"] == "completed"
    assert reopened.get(completed["id"])["result_ids"] == ["done-result"]
    assert reopened._futures == {}


def test_nonwaiting_close_does_not_create_a_competing_worker(queue_env):
    queue = queue_env.create()
    started, release = Event(), Event()

    def runner(job):
        started.set()
        assert release.wait(5)
        return ["result-after-close"]

    job = queue.enqueue("before-close", "content-1", [snapshot()], runner)[0]
    try:
        assert started.wait(5)
        queue.close(wait=False)
        same = queue_env.create()
        assert same is queue
        with pytest.raises(QueueConflictError):
            same.enqueue("too-soon", "content-1", [snapshot()], runner)
    finally:
        release.set()
    wait_status(queue, job["id"], "completed")
    queue.close(wait=True)
    reopened = queue_env.create()
    assert reopened is not queue


def test_enqueue_commit_failure_does_not_execute_or_accept_partial_batch(queue_env, monkeypatch):
    queue = queue_env.create()
    calls: list[str] = []

    def no_commit(jobs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(queue._store, "save_many", no_commit)
    with pytest.raises(RuntimeError, match="disk unavailable"):
        queue.enqueue("not-saved", "content-1", [snapshot()], lambda job: calls.append(job["id"]))
    assert queue.list() == []
    assert calls == []


def test_missing_results_fail_instead_of_reporting_success(queue_env):
    queue = queue_env.create()
    job = queue.enqueue("empty-output", "content-1", [snapshot()], lambda job: [])[0]
    failed = wait_status(queue, job["id"], "failed")
    assert failed["result_ids"] == []
    assert "결과가 없습니다" in failed["message"]


def test_list_is_filtered_bounded_and_leaves_unrelated_settings_intact(queue_env):
    queue = queue_env.create()
    first = queue.enqueue("initial", "other-content", [snapshot()], lambda job: ["output"])[0]
    wait_status(queue, first["id"], "completed")
    template = queue._store.get(first["id"])
    copies = []
    for index in range(110):
        item = deepcopy(template)
        item.update(id=str(uuid4()), batch_id=f"stored-{index}", content_id="content-1")
        copies.append(item)
    queue._store.save_many(copies)
    with queue_env.sessions(queue_env.settings) as session:
        session.add(DbStudioSetting(key="default-menu", value={"menu": "sfx"}, updated_at=datetime.now(timezone.utc)))
    assert len(queue.list()) == 100
    assert len(queue.list("content-1")) == 100
    assert [job["id"] for job in queue.list("other-content")] == [first["id"]]
    with queue_env.sessions(queue_env.settings) as session:
        assert session.get(DbStudioSetting, "default-menu").value == {"menu": "sfx"}
        assert len(session.execute(select(DbStudioSetting.key)).all()) == 112
    with pytest.raises(QueueNotFoundError):
        queue.get("absent-job")


@pytest.mark.parametrize(
    "inputs",
    [
        [],
        [snapshot(), snapshot()],
        [snapshot(text="  ")],
        [{**snapshot(), "request": None}],
        [{**snapshot(), "production_settings": {"speed": float("nan")}}],
    ],
)
def test_invalid_snapshots_never_enter_the_queue(queue_env, inputs):
    queue = queue_env.create()
    with pytest.raises(QueueValidationError):
        queue.enqueue("invalid", "content-1", inputs, lambda job: ["output"])
    assert queue.list() == []
