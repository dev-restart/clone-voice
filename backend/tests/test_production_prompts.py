from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.production_assist import router
from app.config import Settings, get_settings
from app.services.production_prompt_store import (
    BUILTIN_PROMPTS, ProductionPromptStore, PromptConflict, PromptUpdateRequest,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, storage_dir=tmp_path, ai_text_settings_path=tmp_path / "selection.json")


@pytest.fixture
def client(settings):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


def test_read_defaults_does_not_write(settings, client):
    result = client.get("/api/ai/production/prompts")
    assert result.status_code == 200
    data = result.json()
    assert data["revision"] == 0
    assert [t["id"] for t in data["templates"]] == ["sound_effect", "music", "song", "cover"]
    assert all(t["prompt"] == t["default_prompt"] and not t["customized"] for t in data["templates"])
    assert not ProductionPromptStore(settings).path.exists()


def test_save_reopen_restore_only_selected_prompt(settings, client):
    saved = client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {"music": "  Keep sparse piano textures.  ", "song": "Use a repeated singable hook."}})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    store = ProductionPromptStore(settings)
    assert store.snapshot("music") == ("Keep sparse piano textures.", 1)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert "Keep sparse piano" in store.path.read_text()
    restored = client.put("/api/ai/production/prompts", json={"expected_revision": 1, "updates": {"music": None}})
    assert restored.status_code == 200
    assert restored.json()["revision"] == 2
    assert ProductionPromptStore(settings).snapshot("music") == (BUILTIN_PROMPTS["music"], 2)
    assert ProductionPromptStore(settings).snapshot("song")[0] == "Use a repeated singable hook."


def test_stale_update_keeps_saved_value(client, settings):
    assert client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {"cover": "Saved direction."}}).status_code == 200
    response = client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {"cover": "Stale input."}})
    assert response.status_code == 409
    assert ProductionPromptStore(settings).snapshot("cover") == ("Saved direction.", 1)


@pytest.mark.parametrize("payload", [
    {"expected_revision": True, "updates": {"song": "text"}},
    {"expected_revision": -1, "updates": {"song": "text"}},
    {"expected_revision": 0, "updates": {}},
    {"expected_revision": 0, "updates": {"unknown": "private-marker"}},
    {"expected_revision": 0, "updates": {"song": "   "}},
    {"expected_revision": 0, "updates": {"song": "x" * 8001}},
    {"expected_revision": 0, "updates": {"song": 42}},
    {"expected_revision": 0, "updates": {"song": "private-marker\u0000"}},
])
def test_invalid_settings_do_not_reflect_input(client, settings, payload):
    result = client.put("/api/ai/production/prompts", json=payload)
    assert result.status_code == 422
    assert "private-marker" not in result.text
    assert not ProductionPromptStore(settings).path.exists()


def test_untrusted_origin_cannot_write(client, settings):
    result = client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {"song": "changed"}}, headers={"Origin": "https://outside.example"})
    assert result.status_code == 403
    assert not ProductionPromptStore(settings).path.exists()


@pytest.mark.parametrize("raw", ['{', '{}',  '{"version": 1, "revision": -1, "overrides": {}}', '{"version": 1, "revision": 0, "overrides": {"unknown": "secret-marker"}}'])
def test_corrupt_store_is_preserved(settings, client, raw):
    store = ProductionPromptStore(settings)
    store.path.write_text(raw)
    assert client.get("/api/ai/production/prompts").status_code == 503
    response = client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {"music": "New value"}})
    assert response.status_code == 503
    assert "secret-marker" not in response.text
    assert store.path.read_text() == raw


def test_failed_atomic_replace_keeps_previous_value(settings, monkeypatch):
    store = ProductionPromptStore(settings)
    store.update(PromptUpdateRequest(expected_revision=0, updates={"sound_effect": "Original"}))
    before = store.path.read_bytes()
    original_replace = Path.replace
    def deny_prompt_replace(path, destination):
        if Path(destination) == store.path:
            raise PermissionError("simulated permission failure")
        return original_replace(path, destination)
    monkeypatch.setattr(Path, "replace", deny_prompt_replace)
    with pytest.raises(RuntimeError, match="저장"):
        store.update(PromptUpdateRequest(expected_revision=1, updates={"sound_effect": "New"}))
    assert store.path.read_bytes() == before
    assert list(store.path.parent.glob(".production_prompts.json.*.tmp")) == []


def test_concurrent_edits_require_revision(settings):
    def save(value):
        try:
            ProductionPromptStore(settings).update(PromptUpdateRequest(expected_revision=0, updates={"music": value}))
            return "saved"
        except PromptConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["Piano", "Guitar"]))
    assert sorted(results) == ["conflict", "saved"]
    assert ProductionPromptStore(settings).public()["revision"] == 1


def test_symlink_prompt_file_is_not_followed(settings, tmp_path):
    target = tmp_path / "other.json"
    target.write_text('{"version": 1, "revision": 0, "overrides": {}}')
    store = ProductionPromptStore(settings)
    store.path.symlink_to(target)
    with pytest.raises(RuntimeError):
        store.public()
    assert target.read_text() == '{"version": 1, "revision": 0, "overrides": {}}'
