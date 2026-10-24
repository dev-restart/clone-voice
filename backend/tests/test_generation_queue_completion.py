"""Fault-injection coverage for persisted audio and incomplete job metadata.

The real job table uses an isolated SQLite database. Runners only write result
IDs into a fake durable-result index; no speech model or audio adapter is used.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import DbStudioSetting
from app.services import generation_queue as module


def snapshot(language="ko"):
    return {
        "language": language,
        "text": "한 번만 생성해야 하는 대본",
        "request": {"voice_id": "voice-1"},
        "production_settings": {"speed": 1.0},
    }


def wait_idle(queue, timeout=5.0):
    """Wait without polling get(), so metadata repair remains test-controlled."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with queue._lock:
            if not queue._futures:
                return
        time.sleep(0.01)
    pytest.fail("TTS worker did not finish")


@pytest.fixture
def completion_env(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'completion-recovery.sqlite3'}"
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
    owned = []
    outputs = {}
    calls = []
    releases = []

    def recovered(job):
        return deepcopy(outputs.get(job["id"], []))

    def runner(job):
        calls.append(job["id"])
        outputs[job["id"]] = [f'{job["id"]}-{job["language"]}']
        return deepcopy(outputs[job["id"]])

    def create(recover=recovered):
        queue = module.GenerationQueue(settings, recover_result_ids=recover)
        if queue not in owned:
            owned.append(queue)
        return queue

    def seed(queue, status, *, message="원래 모델 오류"):
        job_id = str(uuid4())
        when = datetime.now(timezone.utc).isoformat()
        job = {
            "id": job_id, "batch_id": f"batch-{job_id}",
            "batch_digest": "legacy-fixture", "content_id": "content-1",
            "language": "ko", "status": status, "message": message,
            "result_ids": [], "snapshot": snapshot(), "parent_job_id": None,
            "created_at": when, "updated_at": when,
        }
        queue._store.save_many([job])
        return job

    yield SimpleNamespace(create=create, outputs=outputs, calls=calls,
                          recovered=recovered, runner=runner, seed=seed,
                          releases=releases)
    for release in releases:
        release.set()
    for queue in owned:
        queue.close(wait=True)
    engine.dispose()


def fail_completed_writes(monkeypatch, queue, *, times=None):
    save = queue._store.save_many
    state = {"remaining": times, "attempts": 0, "failed_status_writes": 0}

    def injected(jobs):
        if any(job["status"] == "failed" for job in jobs):
            state["failed_status_writes"] += 1
        if any(job["status"] == "completed" for job in jobs):
            state["attempts"] += 1
            if state["remaining"] is None or state["remaining"] > 0:
                if state["remaining"] is not None:
                    state["remaining"] -= 1
                raise OSError("injected completion metadata commit failure")
        save(jobs)

    monkeypatch.setattr(queue._store, "save_many", injected)
    return state, save


@pytest.mark.parametrize("poll", ["get", "list"])
def test_completion_commit_failure_is_repaired_without_model_retry(completion_env, monkeypatch, poll):
    queue = completion_env.create()
    fault, _ = fail_completed_writes(monkeypatch, queue, times=1)
    job = queue.enqueue("complete-once", "content-1", [snapshot()], completion_env.runner)[0]
    wait_idle(queue)

    # Inference is already durable, but the job commit failed. It must never
    # pass through failed, which would expose a misleading retry action.
    assert queue._store.get(job["id"])["status"] == "running"
    assert completion_env.calls == [job["id"]]
    assert fault["failed_status_writes"] == 0
    public = queue.get(job["id"]) if poll == "get" else queue.list("content-1")[0]
    assert public["status"] == "completed"
    assert public["result_ids"] == completion_env.outputs[job["id"]]
    assert "snapshot" not in public
    assert fault["attempts"] == 2
    duplicate = queue.enqueue("complete-once", "content-1", [snapshot()], completion_env.runner)[0]
    assert duplicate["id"] == job["id"]
    assert duplicate["status"] == "completed"
    assert completion_env.calls == [job["id"]]


def test_persistent_completion_write_failure_never_reexecutes_model(completion_env, monkeypatch):
    queue = completion_env.create()
    fault, save = fail_completed_writes(monkeypatch, queue)
    job = queue.enqueue("metadata-offline", "content-1", [snapshot()], completion_env.runner)[0]
    wait_idle(queue)

    pending = queue.get(job["id"])
    assert pending["status"] == "running"
    assert pending["result_ids"] == completion_env.outputs[job["id"]]
    assert "완료 기록" in pending["message"]
    assert queue.retry(job["id"], "should-not-create", completion_env.runner)["id"] == job["id"]
    assert queue.enqueue("metadata-offline", "content-1", [snapshot()], completion_env.runner)[0]["id"] == job["id"]
    with pytest.raises(module.QueueConflictError):
        queue.cancel(job["id"])
    assert len(queue.list()) == 1
    assert completion_env.calls == [job["id"]]
    assert fault["failed_status_writes"] == 0

    monkeypatch.setattr(queue._store, "save_many", save)
    assert queue.get(job["id"])["status"] == "completed"
    assert queue._store.get(job["id"])["result_ids"] == completion_env.outputs[job["id"]]
    assert completion_env.calls == [job["id"]]


def test_retry_recovers_legacy_failed_job_with_saved_result(completion_env):
    queue = completion_env.create()
    old = completion_env.seed(queue, "failed", message="old completion commit error")
    completion_env.outputs[old["id"]] = ["previously-saved-result"]

    recovered = queue.retry(old["id"], "recovery-only", completion_env.runner)
    assert recovered["id"] == old["id"]
    assert recovered["status"] == "completed"
    assert recovered["result_ids"] == ["previously-saved-result"]
    assert len(queue.list()) == 1
    assert completion_env.calls == []


def test_legacy_failed_job_stays_non_retryable_if_recovery_commit_is_down(completion_env, monkeypatch):
    queue = completion_env.create()
    old = completion_env.seed(queue, "failed")
    completion_env.outputs[old["id"]] = ["previously-saved-result"]
    _, save = fail_completed_writes(monkeypatch, queue)

    first = queue.retry(old["id"], "retry-first", completion_env.runner)
    again = queue.retry(old["id"], "retry-again", completion_env.runner)
    assert first["id"] == again["id"] == old["id"]
    assert first["status"] == again["status"] == "running"
    assert queue._store.get(old["id"])["status"] == "failed"
    assert len(queue.list()) == 1
    assert completion_env.calls == []

    monkeypatch.setattr(queue._store, "save_many", save)
    assert queue.get(old["id"])["status"] == "completed"
    assert completion_env.calls == []


@pytest.mark.parametrize("old_status", ["queued", "running", "failed"])
def test_restart_recovers_durable_output_including_legacy_false_failure(completion_env, old_status):
    queue = completion_env.create()
    old = completion_env.seed(queue, old_status)
    completion_env.outputs[old["id"]] = ["survives-restart"]
    queue.close(wait=True)

    reopened = completion_env.create()
    recovered = reopened.get(old["id"])
    assert reopened is not queue
    assert recovered["status"] == "completed"
    assert recovered["result_ids"] == ["survives-restart"]
    assert completion_env.calls == []
    assert reopened._futures == {}
    with pytest.raises(module.QueueConflictError):
        reopened.retry(old["id"], "must-not-replay", completion_env.runner)


def test_runner_error_after_result_append_recovers_the_saved_audio(completion_env):
    queue = completion_env.create()

    def bookkeeping_fails(job):
        completion_env.runner(job)
        raise RuntimeError("post-generation progress callback failed")

    job = queue.enqueue("post-write-error", "content-1", [snapshot()], bookkeeping_fails)[0]
    wait_idle(queue)
    public = queue.get(job["id"])
    assert public["status"] == "completed"
    assert public["result_ids"] == completion_env.outputs[job["id"]]
    assert completion_env.calls == [job["id"]]


def test_lookup_error_preserves_model_error_and_blocks_retry_until_verified(completion_env):
    lookup_down = {"value": True}

    def recovered(job):
        if lookup_down["value"]:
            raise OSError("recovery database unavailable")
        return completion_env.recovered(job)

    queue = completion_env.create(recovered)
    failures = []

    def model_fails(job):
        failures.append(job["id"])
        raise RuntimeError("실제 모델 메모리 부족 오류")

    job = queue.enqueue("actual-failure", "content-1", [snapshot()], model_fails)[0]
    wait_idle(queue)
    assert queue.get(job["id"])["message"] == "실제 모델 메모리 부족 오류"
    assert queue.get(job["id"])["status"] == "failed"
    with pytest.raises(module.QueueConflictError, match="저장된 음성 결과를 확인하지 못했습니다"):
        queue.retry(job["id"], "blocked-retry", completion_env.runner)
    assert queue.get(job["id"])["message"] == "실제 모델 메모리 부족 오류"
    assert failures == [job["id"]]
    assert completion_env.calls == []
    assert len(queue.list()) == 1

    lookup_down["value"] = False
    retried = queue.retry(job["id"], "verified-retry", completion_env.runner)
    wait_idle(queue)
    assert retried["id"] != job["id"]
    assert retried["parent_job_id"] == job["id"]
    assert queue.get(retried["id"])["status"] == "completed"
    assert queue.get(job["id"])["message"] == "실제 모델 메모리 부족 오류"
    assert completion_env.calls == [retried["id"]]


def test_restart_lookup_error_preserves_failed_message_and_never_replays(completion_env):
    queue = completion_env.create()
    failed = completion_env.seed(queue, "failed", message="원래 생성 엔진 오류")
    interrupted = completion_env.seed(queue, "running", message="이전 프로세스에서 생성 중")
    queue.close(wait=True)

    def unavailable(job):
        raise OSError("temporary lookup failure")

    reopened = completion_env.create(unavailable)
    assert reopened.get(failed["id"])["message"] == "원래 생성 엔진 오류"
    assert reopened.get(interrupted["id"])["status"] == "failed"
    assert "재시작" in reopened.get(interrupted["id"])["message"]
    for old in (failed, interrupted):
        with pytest.raises(module.QueueConflictError):
            reopened.retry(old["id"], f'retry-{old["id"]}', completion_env.runner)
    assert len(reopened.list()) == 2
    assert completion_env.calls == []


def test_cancelled_queued_job_can_retry_without_completion_lookup(completion_env):
    looked_up = []

    def unavailable(job):
        looked_up.append(job["id"])
        raise OSError("must not consult output of cancelled queued work")

    queue = completion_env.create(unavailable)
    started, release = Event(), Event()
    completion_env.releases.append(release)

    def hold_first(job):
        started.set()
        assert release.wait(5)
        return completion_env.runner(job)

    first = queue.enqueue("occupy-worker", "content-1", [snapshot()], hold_first)[0]
    assert started.wait(5)
    cancelled = queue.enqueue("cancel-me", "content-1", [snapshot("en")], completion_env.runner)[0]
    assert queue.cancel(cancelled["id"])["status"] == "cancelled"
    retried = queue.retry(cancelled["id"], "retry-cancelled", completion_env.runner)
    release.set()
    wait_idle(queue)

    assert queue.get(retried["id"])["status"] == "completed"
    assert queue.get(cancelled["id"])["status"] == "cancelled"
    assert completion_env.calls == [first["id"], retried["id"]]
    assert looked_up == []


def test_invalid_recovery_response_does_not_authorize_regeneration(completion_env):
    queue = completion_env.create(lambda job: None)
    old = completion_env.seed(queue, "failed", message="original error")
    with pytest.raises(module.QueueConflictError):
        queue.retry(old["id"], "not-verified", completion_env.runner)
    assert queue.get(old["id"])["message"] == "original error"
    assert len(queue.list()) == 1
    assert completion_env.calls == []


def test_completion_repair_does_not_recreate_a_deleted_job(completion_env, monkeypatch):
    queue = completion_env.create()
    _, save = fail_completed_writes(monkeypatch, queue)
    job = queue.enqueue("removed-record", "content-1", [snapshot()], completion_env.runner)[0]
    wait_idle(queue)
    with module.session_scope(queue._store.settings) as session:
        row = session.get(DbStudioSetting, module.PREFIX + job["id"])
        session.delete(row)

    monkeypatch.setattr(queue._store, "save_many", save)
    assert queue.list() == []
    with pytest.raises(module.QueueNotFoundError):
        queue.get(job["id"])
    assert queue._store.get(job["id"]) is None
    assert completion_env.calls == [job["id"]]
