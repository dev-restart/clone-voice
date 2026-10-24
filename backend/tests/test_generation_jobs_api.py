"""HTTP regressions for editable scripts and persistent TTS jobs.

The real routes, database stores, queue, pronunciation handling, result snapshots,
and result append run here. Only inference is replaced by a controlled WAV writer;
no application startup, model load, translation, ffmpeg, or network is required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
from pathlib import Path
import struct
from threading import Event, Lock
import time
from types import SimpleNamespace
from uuid import uuid4
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_router
from app.api.routes import contents, generation_jobs
from app.config import Settings, get_settings


@dataclass
class BlockedGeneration:
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)


class FakeSynthesis:
    """A controllable inference boundary, preserving all higher-level behavior."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.calls: list[dict] = []
        self.blocks: dict[str, BlockedGeneration] = {}
        self.failures: dict[str, int] = {}
        self.lock = Lock()

    def block(self, text: str) -> BlockedGeneration:
        item = BlockedGeneration()
        self.blocks[text] = item
        return item

    def fail_next(self, text: str) -> None:
        self.failures[text] = self.failures.get(text, 0) + 1

    def release_all(self) -> None:
        for item in self.blocks.values():
            item.release.set()

    async def __call__(self, **kwargs):
        call = {
            key: kwargs.get(key)
            for key in ("text", "language_code", "speed", "tone_prompt", "num_step", "guidance_scale", "progress_id")
        }
        with self.lock:
            self.calls.append(call)
            remaining = self.failures.get(call["text"], 0)
            if remaining:
                self.failures[call["text"]] = remaining - 1
        if remaining:
            raise RuntimeError("회귀 테스트용 일시적 합성 실패")
        blocked = self.blocks.get(call["text"])
        if blocked is not None:
            blocked.started.set()
            if not await asyncio.to_thread(blocked.release.wait, 10):
                raise RuntimeError("테스트에서 대기 중인 합성을 해제하지 않았습니다.")

        self.settings.outputs_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.outputs_dir / f"fake-api-{uuid4().hex}.wav"
        sample_rate, duration = 24000, 0.25
        samples = b"".join(
            struct.pack("<h", int(5000 * math.sin(2 * math.pi * 220 * frame / sample_rate)))
            for frame in range(int(sample_rate * duration))
        )
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(samples)
        return path, duration


@pytest.fixture
def http_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(_env_file=None, storage_dir=tmp_path)
    synthesis = FakeSynthesis(settings)
    engine = SimpleNamespace(engine_name="fake-http-tts")
    application = FastAPI()
    application.include_router(contents.router)
    application.include_router(generation_jobs.router)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_router] = lambda: SimpleNamespace()
    application.dependency_overrides[contents.get_voice_engine] = lambda: engine
    # The queued runner creates its engine directly; the legacy route uses the
    # FastAPI dependency above. Both must stay independent of installed models.
    monkeypatch.setattr(generation_jobs, "get_voice_engine", lambda _settings: engine)
    monkeypatch.setattr(contents, "run_generation_with_progress", synthesis)
    queue = generation_jobs.queue_for(settings)
    with TestClient(application) as client:
        try:
            yield SimpleNamespace(client=client, synthesis=synthesis, settings=settings, queue=queue)
        finally:
            synthesis.release_all()
            queue.close(wait=True)


def create_content(client: TestClient, text: str, *, language: str = "ko", translations: dict | None = None, production: dict | None = None) -> dict:
    response = client.post("/api/contents", json={
        "title": "다국어 음성 API 테스트",
        "source_language": language,
        "source_text": text,
        "translations": translations or {},
        "production_settings": production,
    })
    assert response.status_code == 201, response.text
    return response.json()


def submit(client: TestClient, content: dict, batch: str, languages: list[str], **options) -> list[dict]:
    response = client.post(f"/api/contents/{content['id']}/jobs", json={
        "batch_id": batch,
        "languages": languages,
        "normalize_output": False,
        **options,
    })
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["concurrency"] == 1
    return body["jobs"]


def wait_job(client: TestClient, initial: dict, expected: str = "completed", timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        response = client.get("/api/generation-jobs", params={"content_id": initial["content_id"]})
        assert response.status_code == 200, response.text
        latest = next((job for job in response.json()["jobs"] if job["id"] == initial["id"]), None)
        assert latest is not None, response.text
        if latest["status"] == expected:
            return latest
        if latest["status"] in {"completed", "failed", "cancelled"}:
            pytest.fail(f"Expected {expected}; job ended as {latest}")
        time.sleep(0.01)
    pytest.fail(f"Expected {expected}; last HTTP job state: {latest}")


@pytest.mark.parametrize("entrypoint", ["generate", "jobs"])
def test_non_korean_source_and_its_korean_translation_use_the_correct_text(http_env, entrypoint):
    client = http_env.client
    content = create_content(
        client, "This is the original English script.", language="en",
        translations={"ko": "이 문장이 한국어 번역문입니다."},
    )
    if entrypoint == "generate":
        response = client.post(f"/api/contents/{content['id']}/generate", json={
            "languages": ["en", "ko"], "normalize_output": False,
        })
        assert response.status_code == 200, response.text
    else:
        jobs = submit(client, content, "non-korean-source", ["en", "ko"])
        for job in jobs:
            wait_job(client, job)
    saved = client.get(f"/api/contents/{content['id']}").json()
    assert saved["source_language"] == "en"
    assert {result["language"]: result["text"] for result in saved["results"]} == {
        "en": "This is the original English script.",
        "ko": "이 문장이 한국어 번역문입니다.",
    }
    assert [(call["language_code"], call["text"]) for call in http_env.synthesis.calls] == [
        ("en", "This is the original English script."),
        ("ko", "이 문장이 한국어 번역문입니다."),
    ]


def test_queued_snapshot_survives_patch_and_completion_preserves_latest_draft_and_existing_results(http_env):
    client, synthesis = http_env.client, http_env.synthesis
    original_text = "크론 서비스를 소개합니다."
    original_rule = {"source": "크론", "replacement": "크론 보이스", "language": "ko"}
    content = create_content(client, original_text, translations={"en": "Original translation."}, production={
        "language": "ko", "speed": 1.1, "quality": "balanced", "pronunciation_rules": [original_rule],
    })
    existing_job = submit(client, content, "existing-result", ["ko"])[0]
    existing_result_id = wait_job(client, existing_job)["result_ids"][0]

    blocker = create_content(client, "먼저 실행 중인 별도 대본")
    blocked = synthesis.block(blocker["source_text"])
    first = submit(client, blocker, "occupy-worker", ["ko"])[0]
    assert blocked.started.wait(5)
    job = submit(client, content, "immutable-request", ["ko"], speed=1.4, tone_prompt="차분한 목소리", num_step=32)[0]
    assert job["status"] == "queued"
    assert "snapshot" not in job and "request" not in job and "batch_digest" not in job

    response = client.patch(f"/api/contents/{content['id']}", json={
        "title": "다음 버전의 제목",
        "source_text": "생성 접수 이후 사용자가 저장한 새 원문입니다.",
        "translations": {"en": "The user edited this translation."},
        "production_settings": {
            "language": "ko", "speed": 1.8, "quality": "fast",
            "pronunciation_rules": [{"source": "크론", "replacement": "다음 버전", "language": "ko"}],
        },
    })
    assert response.status_code == 200, response.text
    edited = response.json()
    assert [result["id"] for result in edited["results"]] == [existing_result_id]
    blocked.release.set()
    wait_job(client, first)
    finished = wait_job(client, job)

    saved = client.get(f"/api/contents/{content['id']}").json()
    assert saved["title"] == "다음 버전의 제목"
    assert saved["source_text"] == edited["source_text"]
    assert saved["translations"] == edited["translations"]
    assert saved["production_settings"] == edited["production_settings"]
    assert len(saved["results"]) == 2
    assert existing_result_id in {result["id"] for result in saved["results"]}
    result = next(result for result in saved["results"] if result["id"] == finished["result_ids"][0])
    assert result["text"] == original_text
    assert result["spoken_text"] == "크론 보이스 서비스를 소개합니다."
    assert result["production_settings"]["pronunciation_rules"] == [original_rule]
    assert result["production_settings"]["speed"] == 1.4
    assert result["production_settings"]["quality"] == "high"
    assert result["tone_prompt"] == "차분한 목소리"
    generated = next(call for call in synthesis.calls if call["progress_id"] == job["id"])
    assert generated["text"] == result["spoken_text"]
    assert generated["speed"] == 1.4
    assert generated["num_step"] == 32


def test_batch_resubmission_returns_existing_job_and_changed_settings_conflict(http_env):
    client, synthesis = http_env.client, http_env.synthesis
    content = create_content(client, "같은 요청은 한 번만 생성합니다.")
    blocked = synthesis.block(content["source_text"])
    original = submit(client, content, "one-user-click", ["ko"])[0]
    assert blocked.started.wait(5)
    duplicate = submit(client, content, "one-user-click", ["ko"])[0]
    assert duplicate["id"] == original["id"]
    conflict = client.post(f"/api/contents/{content['id']}/jobs", json={
        "batch_id": "one-user-click", "languages": ["ko"], "normalize_output": False, "speed": 1.3,
    })
    assert conflict.status_code == 409, conflict.text
    listed = client.get("/api/generation-jobs", params={"content_id": content["id"]}).json()["jobs"]
    assert len(listed) == 1
    blocked.release.set()
    wait_job(client, original)
    assert len(synthesis.calls) == 1
    assert len(client.get(f"/api/contents/{content['id']}").json()["results"]) == 1


def test_cancel_waiting_job_and_retry_use_the_original_text_after_editing(http_env):
    client, synthesis = http_env.client, http_env.synthesis
    blocker = create_content(client, "취소 검증을 위해 먼저 실행하는 대본")
    blocked = synthesis.block(blocker["source_text"])
    running = submit(client, blocker, "blocking-request", ["ko"])[0]
    assert blocked.started.wait(5)
    target = create_content(client, "재시도할 원래 접수 대본")
    queued = submit(client, target, "cancel-this-request", ["ko"])[0]
    assert client.post(f"/api/generation-jobs/{running['id']}/cancel").status_code == 409
    cancelled = client.post(f"/api/generation-jobs/{queued['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    patch = client.patch(f"/api/contents/{target['id']}", json={"source_text": "취소 이후 수정한 새 대본"})
    assert patch.status_code == 200, patch.text
    retry_response = client.post(f"/api/generation-jobs/{queued['id']}/retry", json={"batch_id": "retry-cancelled"})
    assert retry_response.status_code == 202, retry_response.text
    retried = retry_response.json()
    assert retried["id"] != queued["id"]
    assert retried["parent_job_id"] == queued["id"]
    blocked.release.set()
    wait_job(client, running)
    wait_job(client, retried)
    saved = client.get(f"/api/contents/{target['id']}").json()
    assert saved["source_text"] == "취소 이후 수정한 새 대본"
    assert [result["text"] for result in saved["results"]] == ["재시도할 원래 접수 대본"]
    assert not any(call["progress_id"] == queued["id"] for call in synthesis.calls)
    assert sum(call["progress_id"] == retried["id"] for call in synthesis.calls) == 1
    wait_job(client, queued, "cancelled")


def test_failed_language_can_retry_without_regenerating_the_successful_language(http_env):
    client, synthesis = http_env.client, http_env.synthesis
    content = create_content(client, "완료된 한국어 결과", translations={"en": "Retry this English sentence."})
    synthesis.fail_next("Retry this English sentence.")
    jobs = submit(client, content, "partial-failure", ["ko", "en"])
    by_language = {job["language"]: job for job in jobs}
    completed = wait_job(client, by_language["ko"])
    wait_job(client, by_language["en"], "failed")
    before = client.get(f"/api/contents/{content['id']}").json()
    assert [result["id"] for result in before["results"]] == completed["result_ids"]
    retried = client.post(f"/api/generation-jobs/{by_language['en']['id']}/retry", json={"batch_id": "retry-only-english"})
    assert retried.status_code == 202, retried.text
    wait_job(client, retried.json())
    saved = client.get(f"/api/contents/{content['id']}").json()
    assert {result["language"] for result in saved["results"]} == {"ko", "en"}
    assert completed["result_ids"][0] in {result["id"] for result in saved["results"]}
    assert [call["language_code"] for call in synthesis.calls] == ["ko", "en", "en"]


@pytest.mark.parametrize("phase", ["queued", "running"])
def test_deleting_content_before_generation_finishes_never_recreates_it(http_env, phase):
    client, synthesis = http_env.client, http_env.synthesis
    target = create_content(client, "삭제할 콘텐츠의 대본")
    if phase == "queued":
        blocker = create_content(client, "삭제 검증을 위해 먼저 실행하는 대본")
        blocked = synthesis.block(blocker["source_text"])
        preceding = submit(client, blocker, "delete-blocker", ["ko"])[0]
        assert blocked.started.wait(5)
        target_job = submit(client, target, "delete-target", ["ko"])[0]
        assert target_job["status"] == "queued"
    else:
        blocked = synthesis.block(target["source_text"])
        target_job = submit(client, target, "delete-target", ["ko"])[0]
        assert blocked.started.wait(5)
        preceding = None
    response = client.delete(f"/api/contents/{target['id']}")
    assert response.status_code == 204, response.text
    blocked.release.set()
    if preceding is not None:
        wait_job(client, preceding)
    failed = wait_job(client, target_job, "failed")
    assert "삭제" in failed["message"]
    assert failed["result_ids"] == []
    assert client.get(f"/api/contents/{target['id']}").status_code == 404
    assert target["id"] not in {item["id"] for item in client.get("/api/contents").json()}
    target_calls = [call for call in synthesis.calls if call["progress_id"] == target_job["id"]]
    assert len(target_calls) == (0 if phase == "queued" else 1)


def test_missing_translation_rejects_the_whole_batch_without_partial_generation(http_env):
    client = http_env.client
    content = create_content(client, "日本語の原稿です。", language="ja")
    response = client.post(f"/api/contents/{content['id']}/jobs", json={
        "batch_id": "missing-korean-translation", "languages": ["ja", "ko"], "normalize_output": False,
    })
    assert response.status_code == 422, response.text
    assert "ko" in response.json()["detail"]
    assert client.get("/api/generation-jobs", params={"content_id": content["id"]}).json()["jobs"] == []
    assert client.get(f"/api/contents/{content['id']}").json()["results"] == []
    assert http_env.synthesis.calls == []
