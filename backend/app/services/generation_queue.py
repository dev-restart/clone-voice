"""Persistent, snapshot-based TTS queue for one local backend process.

All queues for the same database share one manager and one worker. Run only one
backend process per storage database; this is not a distributed worker lease.
The caller owns generation, inference locking, and atomic content-result append.
It must append under the immutable job id before returning result ids here.

Unfinished records from an earlier manager lifetime are reconciled against the
caller's durable results on startup, never silently replayed. The recovery
callback is also checked before retrying a failed job. After a runner returns,
completion-record failures are retried without invoking the runner again.
A normal close stops accepting/starting work; already running model calls can
finish. ``close(wait=False)`` does not stop model threads. Recovery after a
process exit requires the caller's ``recover_result_ids`` callback.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from threading import RLock, Timer
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import select

from app.config import Settings
from app.db.models import DbStudioSetting
from app.db.session import session_scope
from app.i18n import tr
from app.services.generation_events import GenerationEvents
from app.services.progress import observe_progress


PREFIX = "tts-job:"
MAX_ACTIVE_JOBS = 32
MAX_LIST_JOBS = 100
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_LANGUAGE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")
_ACTIVE = {"queued", "running"}
_STATUSES = _ACTIVE | {"completed", "failed", "cancelled"}
_PUBLIC_FIELDS = (
    "id", "batch_id", "content_id", "language", "status", "message",
    "result_ids", "created_at", "updated_at", "parent_job_id",
)
_INTERRUPTED = "서버가 재시작되어 작업이 중단되었습니다. 다시 시도해 주세요."
_COMPLETION_PENDING = "음성은 생성되었습니다. 완료 기록을 다시 저장하고 있습니다."
_RECOVERY_UNAVAILABLE = "저장된 음성 결과를 확인하지 못했습니다. 중복 생성을 방지하기 위해 잠시 후 다시 시도해 주세요."
_logger = logging.getLogger(__name__)

Job = dict[str, Any]
Runner = Callable[[Job], Any]
_registry_lock = RLock()
_registry: dict[str, "GenerationQueue"] = {}


class QueueError(RuntimeError):
    status_code = 500


class QueueValidationError(QueueError):
    status_code = 422


class QueueConflictError(QueueError):
    status_code = 409


class QueueNotFoundError(QueueError):
    status_code = 404


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        english = {"요청 ID": "request ID", "콘텐츠 ID": "content ID", "작업 ID": "job ID"}.get(label, label)
        raise QueueValidationError(tr(f"{label}가 올바르지 않습니다.", f"The {english} is not valid."))
    return value


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise QueueValidationError(tr("생성 요청에는 저장 가능한 값만 사용할 수 있습니다.", "Only storable values can be used in a generation request.")) from exc


def _snapshots(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ACTIVE_JOBS:
        raise QueueValidationError(tr(f"한 번에 1~{MAX_ACTIVE_JOBS}개 언어를 요청할 수 있습니다.", f"You can request 1–{MAX_ACTIVE_JOBS} languages at a time."))
    result: list[dict[str, Any]] = []
    languages: set[str] = set()
    for incoming in value:
        if not isinstance(incoming, dict):
            raise QueueValidationError(tr("언어별 생성 요청이 올바르지 않습니다.", "The per-language generation request is not valid."))
        language = incoming.get("language")
        if not isinstance(language, str) or not _LANGUAGE.fullmatch(language):
            raise QueueValidationError(tr("생성 언어가 올바르지 않습니다.", "The generation language is not valid."))
        if language in languages:
            raise QueueValidationError(tr("같은 언어를 한 번의 요청에 중복해서 넣을 수 없습니다.", "The same language cannot appear twice in one request."))
        text = incoming.get("text")
        if not isinstance(text, str) or not text.strip():
            raise QueueValidationError(tr("음성으로 만들 대본을 입력해 주세요.", "Enter the script to turn into speech."))
        if not isinstance(incoming.get("request"), dict):
            raise QueueValidationError(tr("음성 생성 설정이 올바르지 않습니다.", "The speech generation settings are not valid."))
        if not isinstance(incoming.get("production_settings"), dict):
            raise QueueValidationError(tr("음성 제작 설정이 올바르지 않습니다.", "The speech production settings are not valid."))
        # Retain optional revision/fingerprint fields, but never retain caller
        # owned mutable objects. Text whitespace is intentional model input.
        result.append(_json_copy(incoming))
        languages.add(language)
    return result


def _digest(content_id: str, snapshots: list[dict[str, Any]]) -> str:
    # Language ordering is presentation, not a new generation request.
    payload = {"content_id": content_id, "snapshots": sorted(snapshots, key=lambda item: item["language"])}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _public(job: Job) -> Job:
    # A strict allowlist prevents scripts, reference paths, and model settings
    # from being returned by status/list endpoints.
    return {key: deepcopy(job.get(key)) for key in _PUBLIC_FIELDS}


def _result_ids(result: Any) -> list[str]:
    if not isinstance(result, (list, tuple)) or not result:
        raise QueueError(tr("생성된 음성 결과가 없습니다.", "No speech result was generated."))
    ids: list[str] = []
    for item in result:
        identifier = item if isinstance(item, str) else item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise QueueError(tr("생성된 음성 결과 ID가 올바르지 않습니다.", "The generated speech result ID is not valid."))
        if identifier not in ids:
            ids.append(identifier)
    return ids


class QueueStore:
    """Job records occupy independent DbStudioSetting rows.

    Calls that form a read-modify-write operation are protected by the manager's
    lock. ``save_many`` commits the whole batch, so rejected submissions cannot
    leave a partly accepted batch behind.
    """

    def __init__(self, settings: Settings, on_change: Callable[[], None] | None = None):
        self.settings = settings
        self.on_change = on_change

    @staticmethod
    def _decode(key: str, value: object) -> Job:
        if not isinstance(value, dict) or key != PREFIX + str(value.get("id", "")):
            raise QueueError(tr("음성 작업 저장 데이터를 읽지 못했습니다. 원본 데이터는 보존되어 있습니다.", "Could not read the saved speech job data. The original data is preserved."))
        if value.get("status") not in _STATUSES or not isinstance(value.get("snapshot"), dict):
            raise QueueError(tr("음성 작업 저장 데이터 형식이 올바르지 않습니다.", "The saved speech job data format is not valid."))
        return deepcopy(value)

    def all(self) -> list[Job]:
        with session_scope(self.settings) as session:
            rows = session.execute(
                select(DbStudioSetting.key, DbStudioSetting.value).where(DbStudioSetting.key.startswith(PREFIX))
            ).all()
            return [self._decode(key, value) for key, value in rows]

    def get(self, job_id: str) -> Job | None:
        with session_scope(self.settings) as session:
            row = session.get(DbStudioSetting, PREFIX + job_id)
            return self._decode(row.key, row.value) if row is not None else None

    def save_many(self, jobs: list[Job]) -> None:
        with session_scope(self.settings) as session:
            for job in jobs:
                key = PREFIX + job["id"]
                row = session.get(DbStudioSetting, key)
                when = datetime.fromisoformat(job["updated_at"])
                if row is None:
                    session.add(DbStudioSetting(key=key, value=deepcopy(job), updated_at=when))
                else:
                    row.value = deepcopy(job)
                    row.updated_at = when
        # Publish only after session_scope committed the transaction.
        if self.on_change is not None:
            self.on_change()


class GenerationQueue:
    """A singleton per ``settings.resolved_database_url`` in this process.

    The runner receives a private deep copy of the complete job. Immutable input
    is in ``job['snapshot']`` with ``language``, ``text``, ``request`` and
    ``production_settings``. Return a nonempty list of result ids, mappings with
    an ``id``, or result objects with an ``id`` attribute. Result persistence and
    target-deletion checks belong to the runner, before it returns.
    """

    def __new__(cls, settings: Settings, recover_result_ids: Callable[[Job], list[str]] | None = None):
        key = str(settings.resolved_database_url)
        with _registry_lock:
            if key in _registry:
                return _registry[key]
            instance = super().__new__(cls)
            instance._database_key = key
            instance._initialized = False
            _registry[key] = instance
            return instance

    def __init__(self, settings: Settings, recover_result_ids: Callable[[Job], list[str]] | None = None):
        with _registry_lock:
            if self._initialized:
                # A status-only caller may have created the singleton before
                # the application supplied its durable-result lookup.
                if recover_result_ids is not None:
                    with self._lock:
                        if self._recover_result_ids is None:
                            self._recover_result_ids = recover_result_ids
                return
            try:
                self._lock = RLock()
                self.events = GenerationEvents()
                self._store = QueueStore(settings, self.events.notify)
                self._progress: dict[str, dict] = {}
                self._completion_retry_timer: Timer | None = None
                self._completion_retry_delay = 2.0
                self._closed = False
                self._futures: dict[str, Future[Any]] = {}
                self._recover_result_ids = recover_result_ids
                self._pending_completions: dict[str, list[str]] = {}
                interrupted: list[Job] = []
                for job in self._store.all():
                    # Older versions could mark a successfully persisted
                    # result failed when the final job-state commit failed.
                    if job["status"] not in _ACTIVE | {"failed"}:
                        continue
                    lookup_failed = False
                    try:
                        ids = self._recovered_ids(job)
                    except Exception:
                        _logger.exception("Could not verify stored results for TTS queue job %s", job["id"])
                        ids = []
                        lookup_failed = True
                    if ids:
                        job.update(status="completed", message=tr("저장된 음성 결과를 복구했습니다.", "Recovered the saved speech result."), result_ids=ids, updated_at=_now(), error_code=None)
                    elif job["status"] in _ACTIVE:
                        message = f"서버가 재시작되어 작업이 중단되었습니다. {_RECOVERY_UNAVAILABLE}" if lookup_failed else _INTERRUPTED
                        job.update(status="failed", message=message, result_ids=[], updated_at=_now(), error_code="recovery_unavailable" if lookup_failed else "interrupted")
                    else:
                        # Preserve the original model failure, including when
                        # looking up its possible output is temporarily down.
                        continue
                    interrupted.append(job)
                if interrupted:
                    self._store.save_many(interrupted)
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clone-voice-tts")
                self._initialized = True
            except Exception:
                if _registry.get(self._database_key) is self:
                    _registry.pop(self._database_key, None)
                raise

    def _require_open(self) -> None:
        if self._closed:
            raise QueueConflictError(tr("음성 작업 대기열이 종료 중입니다. 잠시 후 다시 시도해 주세요.", "The speech queue is shutting down. Try again shortly."))

    def _require_job(self, job_id: str) -> Job:
        job = self._store.get(_identifier(job_id, "작업 ID"))
        if job is None:
            raise QueueNotFoundError(tr("음성 생성 작업을 찾을 수 없습니다.", "The speech generation job was not found."))
        return job

    def _recovered_ids(self, job: Job) -> list[str]:
        if self._recover_result_ids is None:
            return []
        result = self._recover_result_ids(deepcopy(job))
        if isinstance(result, (list, tuple)) and not result:
            return []
        # A broken lookup must not be interpreted as proof that no output was
        # saved: doing so could make retry run the model a second time.
        return _result_ids(result)

    def _public_job(self, job: Job) -> Job:
        public = _public(job)
        if job["status"] in _ACTIVE and job["id"] in self._progress:
            public["progress"] = deepcopy(self._progress[job["id"]])
        if job["id"] in self._pending_completions:
            public.update(status="running", message=_COMPLETION_PENDING,
                          result_ids=deepcopy(self._pending_completions[job["id"]]))
        return public

    def _flush_completion(self, job_id: str) -> None:
        """Retry only the completion commit; caller holds ``self._lock``."""
        ids = self._pending_completions.get(job_id)
        if ids is None:
            return
        try:
            current = self._store.get(job_id)
            if current is not None and current["status"] not in {"completed", "cancelled"}:
                current.update(status="completed", message=tr("음성 생성이 완료되었습니다.", "Speech generation is complete."),
                               result_ids=deepcopy(ids), updated_at=_now(), error_code=None)
                self._store.save_many([current])
            # Never recreate a deleted record or reverse an explicit cancel.
            self._pending_completions.pop(job_id, None)
        except Exception:
            # Keep the proof that generation finished. Public status remains
            # non-retryable and later polling retries this metadata write only.
            _logger.exception("Could not persist completion for TTS queue job %s; retaining result ids", job_id)

    def _remember_completion(self, job_id: str, ids: list[str]) -> None:
        self._pending_completions[job_id] = deepcopy(ids)
        self._flush_completion(job_id)
        self.events.notify()
        self._schedule_completion_retry()

    def _schedule_completion_retry(self) -> None:
        # Completion persistence must not depend on a browser polling the queue.
        if self._closed or not self._pending_completions or self._completion_retry_timer is not None:
            return
        timer = Timer(self._completion_retry_delay, self._retry_completions)
        timer.daemon = True
        self._completion_retry_timer = timer
        timer.start()

    def _retry_completions(self) -> None:
        with self._lock:
            self._completion_retry_timer = None
            if self._closed:
                return
            self._flush_pending_completions()
            self._completion_retry_delay = min(30.0, self._completion_retry_delay * 2) if self._pending_completions else 2.0
            self._schedule_completion_retry()

    def _report_progress(self, job_id: str, payload: dict) -> None:
        with self._lock:
            self._progress[job_id] = {
                "percent": max(0, min(99, int(payload.get("percent", 0)))),
                "message": str(payload.get("message", ""))[:500],
                "timestamp": str(payload.get("timestamp", "")),
            }
            self.events.notify()

    def _flush_pending_completions(self) -> None:
        for job_id in list(self._pending_completions):
            self._flush_completion(job_id)

    def enqueue(self, batch_id: str, content_id: str, snapshots: list[dict[str, Any]], runner: Runner) -> list[Job]:
        return self._enqueue(batch_id, content_id, snapshots, runner, parent_job_id=None)

    def _enqueue(self, batch_id: str, content_id: str, snapshots: list[dict[str, Any]], runner: Runner, *, parent_job_id: str | None) -> list[Job]:
        batch_id = _identifier(batch_id, "요청 ID")
        content_id = _identifier(content_id, "콘텐츠 ID")
        inputs = _snapshots(snapshots)
        fingerprint = _digest(content_id, inputs)
        if not callable(runner):
            raise QueueValidationError(tr("음성 생성 실행 함수가 필요합니다.", "A speech generation runner is required."))
        with self._lock:
            self._require_open()
            self._flush_pending_completions()
            jobs = self._store.all()
            existing = [job for job in jobs if job["batch_id"] == batch_id]
            if existing:
                if any(job.get("batch_digest") != fingerprint or job.get("parent_job_id") != parent_job_id for job in existing):
                    raise QueueConflictError(tr("같은 요청 ID에 다른 대본이나 설정을 사용할 수 없습니다. 새 요청으로 생성해 주세요.", "The same request ID cannot be used with a different script or settings. Start a new request."))
                by_language = {job["language"]: job for job in existing}
                if set(by_language) != {item["language"] for item in inputs}:
                    raise QueueConflictError(tr("저장된 언어 요청과 일치하지 않습니다. 새 요청으로 생성해 주세요.", "This does not match the saved language request. Start a new request."))
                return [self._public_job(by_language[item["language"]]) for item in inputs]
            if sum(job["status"] in _ACTIVE for job in jobs) + len(inputs) > MAX_ACTIVE_JOBS:
                raise QueueConflictError(tr(f"대기 중이거나 생성 중인 작업은 최대 {MAX_ACTIVE_JOBS}개입니다. 완료 후 다시 시도해 주세요.", f"At most {MAX_ACTIVE_JOBS} jobs can be queued or running. Try again after some finish."))
            now = _now()
            new_jobs: list[Job] = [
                {
                    "id": str(uuid4()), "batch_id": batch_id, "batch_digest": fingerprint,
                    "content_id": content_id, "language": snapshot["language"],
                    "status": "queued", "message": tr("음성 생성 순서를 기다리고 있습니다.", "Waiting for its turn to generate."),
                    "result_ids": [], "snapshot": snapshot, "parent_job_id": parent_job_id,
                    "created_at": now, "updated_at": now,
                }
                for snapshot in inputs
            ]
            self._store.save_many(new_jobs)
            # Persist before any worker can start. The lock also makes submit
            # atomic with close/cancel and the worker's queued -> running claim.
            for index, job in enumerate(new_jobs):
                try:
                    future = self._executor.submit(contextvars.copy_context().run, self._execute, job["id"], runner)
                    self._futures[job["id"]] = future
                    future.add_done_callback(lambda completed, job_id=job["id"]: self._finished(job_id, completed))
                except Exception as exc:
                    unscheduled = new_jobs[index:]
                    for pending in unscheduled:
                        pending.update(status="failed", message=tr("음성 작업을 시작하지 못했습니다. 다시 시도해 주세요.", "Could not start the speech job. Try again."), updated_at=_now())
                    self._store.save_many(unscheduled)
                    raise QueueError(tr("음성 작업을 시작하지 못했습니다.", "Could not start the speech job.")) from exc
            return [_public(job) for job in new_jobs]

    def list(self, content_id: str | None = None) -> list[Job]:
        if content_id is not None:
            _identifier(content_id, "콘텐츠 ID")
        with self._lock:
            self._flush_pending_completions()
            jobs = self._store.all()
            if content_id is not None:
                jobs = [job for job in jobs if job["content_id"] == content_id]
            # A long-running job must not disappear behind recent finished jobs.
            jobs.sort(key=lambda job: (job["status"] in _ACTIVE, job["created_at"], job["id"]), reverse=True)
            return [self._public_job(job) for job in jobs[:MAX_LIST_JOBS]]

    def get(self, job_id: str) -> Job:
        with self._lock:
            self._flush_completion(job_id)
            return self._public_job(self._require_job(job_id))

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            self._require_open()
            job = self._require_job(job_id)
            if job["status"] == "cancelled":
                return _public(job)
            if job["status"] != "queued":
                raise QueueConflictError(tr("대기 중인 작업만 취소할 수 있습니다. 이미 시작된 작업은 완료될 때까지 기다려 주세요.", "Only queued jobs can be cancelled. Wait for a job that has already started to finish."))
            job.update(status="cancelled", message=tr("대기 중인 음성 생성을 취소했습니다.", "Cancelled the queued speech generation."), updated_at=_now())
            self._store.save_many([job])
            future = self._futures.get(job_id)
            if future is not None:
                future.cancel()
            return _public(job)

    def retry(self, job_id: str, new_batch_id: str, runner: Runner) -> Job:
        with self._lock:
            self._require_open()
            new_batch_id = _identifier(new_batch_id, "요청 ID")
            self._flush_completion(job_id)
            old = self._require_job(job_id)
            if job_id in self._pending_completions:
                return self._public_job(old)
            if old["status"] not in {"failed", "cancelled"}:
                raise QueueConflictError(tr("실패하거나 취소된 작업만 다시 시도할 수 있습니다.", "Only failed or cancelled jobs can be retried."))
            if new_batch_id == old["batch_id"]:
                raise QueueConflictError(tr("다시 시도할 때는 새 요청 ID를 사용해 주세요.", "Use a new request ID when retrying."))
            if old["status"] == "failed":
                try:
                    ids = self._recovered_ids(old)
                except Exception as exc:
                    _logger.exception("Could not verify TTS queue job %s before retry", job_id)
                    raise QueueConflictError(_RECOVERY_UNAVAILABLE) from exc
                if ids:
                    self._remember_completion(job_id, ids)
                    return self._public_job(self._require_job(job_id))
            return self._enqueue(new_batch_id, old["content_id"], [deepcopy(old["snapshot"])], runner, parent_job_id=old["id"])[0]

    def _execute(self, job_id: str, runner: Runner) -> None:
        try:
            with self._lock:
                job = self._require_job(job_id)
                if self._closed or job["status"] != "queued":
                    return
                job.update(status="running", message=tr("음성을 만들고 있습니다.", "Generating speech."), updated_at=_now())
                self._store.save_many([job])
                submitted = deepcopy(job)
            with observe_progress(job_id, lambda payload: self._report_progress(job_id, payload)):
                ids = _result_ids(runner(submitted))
        except Exception as exc:
            _logger.exception("TTS queue job %s failed", job_id)
            try:
                with self._lock:
                    current = self._store.get(job_id)
                    if current is not None and current["status"] in _ACTIVE:
                        # A runner can persist audio before a final bookkeeping
                        # step raises. Prefer its durable output when verifiable.
                        try:
                            recovered = self._recovered_ids(current)
                        except Exception:
                            recovered = []
                            _logger.exception("Could not verify results after failure of TTS queue job %s", job_id)
                        if recovered:
                            self._remember_completion(job_id, recovered)
                            return
                        detail = str(exc).strip()[:500] or tr("음성 생성에 실패했습니다. 다시 시도해 주세요.", "Speech generation failed. Try again.")
                        current.update(status="failed", message=detail, updated_at=_now(), error_code="generation_failed")
                        self._store.save_many([current])
            except Exception:
                _logger.exception("Could not persist failure for TTS queue job %s", job_id)
            return
        # This write is deliberately outside the runner's exception handler.
        # Successful inference must never turn into a retryable model failure
        # just because its final job-state transaction could not commit.
        with self._lock:
            self._remember_completion(job_id, ids)

    def _finished(self, job_id: str, future: Future[Any]) -> None:
        with self._lock:
            self._futures.pop(job_id, None)
            self._progress.pop(job_id, None)
            release = self._closed and not self._futures
        if release:
            with _registry_lock:
                if _registry.get(self._database_key) is self:
                    _registry.pop(self._database_key, None)

    def close(self, wait: bool = True) -> None:
        """Stop new work; pending persisted jobs are recovered on next startup.

        Non-waiting close cannot interrupt a running model. Its manager remains
        registered until the worker finishes, preventing a second manager from
        executing concurrently against the same database in this process.
        """
        with self._lock:
            self._closed = True
            if self._completion_retry_timer is not None:
                self._completion_retry_timer.cancel()
                self._completion_retry_timer = None
        self._executor.shutdown(wait=wait, cancel_futures=True)
        with self._lock:
            self._flush_pending_completions()
            release = not self._futures
        if release:
            with _registry_lock:
                if _registry.get(self._database_key) is self:
                    _registry.pop(self._database_key, None)



def close_generation_queues(wait: bool = False) -> None:
    with _registry_lock:
        queues = list(_registry.values())
    for queue in queues:
        queue.close(wait=wait)
