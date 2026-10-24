"""Exercise generation/project persistence with synthetic output, without models."""

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_router
from app.api.routes import sound_effects, sound_projects
from app.config import Settings, get_settings
from app.services.sound_project_store import SoundAsset, SoundProject, SoundProjectConflict, SoundProjectStore


class SyntheticSoundAdapter:
    """Only the expensive model boundary is replaced; metadata uses the real DB."""

    label = "Synthetic sound test adapter"

    def __init__(self, settings: Settings):
        self.outputs_dir = Path(settings.outputs_dir)
        self.calls: list[dict] = []
        self.during_generation: Callable[[], None] | None = None

    def status(self):
        return SimpleNamespace(capabilities=SimpleNamespace(sound_effect_generation=True))

    def generate_sound_effect(self, **kwargs):
        self.calls.append(kwargs)
        callback, self.during_generation = self.during_generation, None
        if callback is not None:
            callback()
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        output = self.outputs_dir / f"project-api-test-{len(self.calls)}.wav"
        # These tests assert output retention and response linkage, not audio
        # validity or model quality. No parser or player consumes these bytes.
        output.write_bytes(b"synthetic generated output")
        return SimpleNamespace(path=output, duration_seconds=kwargs["duration_seconds"])


@pytest.fixture
def sound_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(_env_file=None, storage_dir=tmp_path)
    adapter = SyntheticSoundAdapter(settings)
    store = SoundProjectStore(settings)

    def available(_router, model_id, capability):
        assert model_id == "stable-audio-sfx"
        assert capability == "sound_effect_generation"
        return adapter

    def plan(prompt, _settings, *, auto_duration, requested_duration):
        return SimpleNamespace(
            source_prompt=prompt,
            generation_prompt=f"Planned: {prompt}",
            duration_seconds=requested_duration or 2.0,
            duration_mode="auto" if auto_duration else "manual",
            translated=False,
            planner="direct",
            provider=None,
            model=None,
        )

    monkeypatch.setattr(sound_effects, "ensure_adapter_available", available)
    monkeypatch.setattr(sound_effects, "plan_sound_effect_prompt", plan)
    monkeypatch.setattr(sound_effects, "publish_progress", lambda *_args, **_kwargs: None)
    application = FastAPI()
    application.include_router(sound_projects.router)
    application.include_router(sound_effects.router)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_router] = lambda: object()
    with TestClient(application) as client:
        yield SimpleNamespace(client=client, store=store, adapter=adapter, settings=settings)


def create_project(client: TestClient, project_id: str = "project-1") -> dict:
    project = SoundProject(
        id=project_id,
        title="게임 효과음",
        category="game",
        assets=[SoundAsset(id="asset-1", title="버튼 클릭", category="ui", prompt="Original click prompt")],
    )
    response = client.put(f"/api/sound-projects/{project_id}", json=project.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    return response.json()


def generation_request(**changes) -> dict:
    return {
        "prompt": "Original click prompt",
        "negative_prompt": "speech, music",
        "duration_seconds": 2,
        "auto_duration": False,
        "steps": 8,
        "guidance_scale": 3,
        "seed": 100,
        "variations": 1,
        **changes,
    }


def assert_retained_output(environment, result: dict) -> None:
    assert result["audio_url"].startswith("/api/files/outputs/")
    path = Path(environment.settings.outputs_dir) / result["audio_url"].rsplit("/", 1)[-1]
    assert path.read_bytes() == b"synthetic generated output"


def test_project_generation_and_prompt_edits_preserve_immutable_versions(sound_api) -> None:
    client = sound_api.client
    created = create_project(client)
    response = client.post(
        "/api/sound-effects/generate",
        json=generation_request(project_id=created["id"], asset_id="asset-1", variations=2),
    )
    assert response.status_code == 200, response.text
    generated = response.json()
    assert generated["storage_warning"] is None
    assert len(generated["results"]) == 2
    assert [item["seed"] for item in generated["results"]] == [100, 101]
    assert generated["project"]["revision"] == 2
    assert generated["project"]["assets"][0]["results"] == generated["results"]
    assert sound_api.adapter.calls[0]["prompt"] == "Planned: Original click prompt"

    edited = generated["project"]
    edited["assets"][0]["prompt"] = "Edited metallic click prompt"
    edited["assets"][0]["results"][0]["prompt"] = "Accidental snapshot overwrite"
    edited["assets"][0]["results"][0]["audio_url"] = "/api/files/outputs/wrong.wav"
    updated = client.put(f"/api/sound-projects/{created['id']}", json=edited)
    assert updated.status_code == 200, updated.text
    saved = updated.json()
    assert saved["assets"][0]["prompt"] == "Edited metallic click prompt"
    assert saved["assets"][0]["results"][0]["prompt"] == "Original click prompt"
    assert saved["assets"][0]["results"][0]["audio_url"] == generated["results"][0]["audio_url"]

    regenerated = client.post(
        "/api/sound-effects/generate",
        json=generation_request(project_id=created["id"], asset_id="asset-1", prompt="Edited metallic click prompt"),
    )
    assert regenerated.status_code == 200, regenerated.text
    history = regenerated.json()["project"]["assets"][0]["results"]
    assert [item["prompt"] for item in history] == ["Original click prompt", "Original click prompt", "Edited metallic click prompt"]
    assert len({item["id"] for item in history}) == 3


def test_prompt_edited_while_generation_runs_is_not_overwritten(sound_api) -> None:
    created = create_project(sound_api.client)

    def edit_during_generation():
        project = sound_api.store.get(created["id"])
        project.assets[0].prompt = "Draft for the next generation"
        project.assets[0].title = "다음 버전의 버튼"
        sound_api.store.save(project.id, project)

    sound_api.adapter.during_generation = edit_during_generation
    response = sound_api.client.post(
        "/api/sound-effects/generate",
        json=generation_request(project_id=created["id"], asset_id="asset-1"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    asset = body["project"]["assets"][0]
    assert body["project"]["revision"] == 3
    assert asset["prompt"] == "Draft for the next generation"
    assert asset["title"] == "다음 버전의 버튼"
    assert asset["results"][0]["prompt"] == "Original click prompt"
    assert body["storage_warning"] is None


def test_deleting_project_or_asset_during_generation_keeps_successful_audio(sound_api) -> None:
    for destination in ("project", "asset"):
        project_id = f"delete-{destination}"
        create_project(sound_api.client, project_id)

        def remove_target():
            project = sound_api.store.get(project_id)
            if destination == "project":
                sound_api.store.delete(project.id, project.revision)
            else:
                project.assets = []
                sound_api.store.save(project.id, project)

        sound_api.adapter.during_generation = remove_target
        response = sound_api.client.post(
            "/api/sound-effects/generate",
            json=generation_request(project_id=project_id, asset_id="asset-1"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["project"] is None
        assert body["storage_warning"]
        assert len(body["results"]) == 1
        assert_retained_output(sound_api, body["results"][0])
        current = sound_api.client.get(f"/api/sound-projects/{project_id}")
        if destination == "project":
            assert current.status_code == 404
        else:
            assert current.status_code == 200
            assert current.json()["assets"] == []


def test_invalid_or_missing_project_asset_pairs_fail_before_generation(sound_api) -> None:
    create_project(sound_api.client)
    invalid_pairs = [
        {"project_id": "project-1"},
        {"asset_id": "asset-1"},
        {"project_id": "../outside", "asset_id": "asset-1"},
        {"project_id": "project-1", "asset_id": "bad/path"},
    ]
    for pair in invalid_pairs:
        response = sound_api.client.post("/api/sound-effects/generate", json=generation_request(**pair))
        assert response.status_code == 422, response.text
    for pair in (
        {"project_id": "missing-project", "asset_id": "asset-1"},
        {"project_id": "project-1", "asset_id": "missing-asset"},
    ):
        response = sound_api.client.post("/api/sound-effects/generate", json=generation_request(**pair))
        assert response.status_code == 404, response.text
    assert sound_api.adapter.calls == []


def test_existing_generation_without_a_project_stays_compatible(sound_api) -> None:
    response = sound_api.client.post("/api/sound-effects/generate", json=generation_request())
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    assert body["project"] is None
    assert body["storage_warning"] is None
    assert body["plan"]["generation_prompt"] == "Planned: Original click prompt"
    assert sound_api.store.list() == []
    assert_retained_output(sound_api, body["results"][0])


def test_persistence_conflict_does_not_regenerate_or_hide_completed_audio(sound_api, monkeypatch: pytest.MonkeyPatch) -> None:
    created = create_project(sound_api.client)

    def fail_metadata_save(self, project_id, asset_id, results):
        raise SoundProjectConflict("다른 작업이 프로젝트를 변경했습니다.")

    monkeypatch.setattr(SoundProjectStore, "save_result", fail_metadata_save)
    response = sound_api.client.post(
        "/api/sound-effects/generate",
        json=generation_request(project_id=created["id"], asset_id="asset-1"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"] is None
    assert "다른 작업" in body["storage_warning"]
    assert len(body["results"]) == 1
    assert len(sound_api.adapter.calls) == 1
    assert_retained_output(sound_api, body["results"][0])
    assert sound_api.store.get(created["id"]).assets[0].results == []

def test_a_later_failed_variation_preserves_successful_audio_and_prompt_metadata(sound_api, monkeypatch):
    create_project(sound_api.client)
    original = sound_api.adapter.generate_sound_effect
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second-variation failure")
        return original(**kwargs)

    monkeypatch.setattr(sound_api.adapter, "generate_sound_effect", fail_second)
    response = sound_api.client.post("/api/sound-effects/generate", json=generation_request(
        project_id="project-1", asset_id="asset-1", variations=3,
    ))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["results"]) == 1
    assert "3개 중 1개" in payload["generation_warning"]
    assert payload["storage_warning"] is None
    assert_retained_output(sound_api, payload["results"][0])
    saved = sound_api.client.get("/api/sound-projects/project-1").json()
    assert saved["assets"][0]["results"] == payload["results"]
    assert saved["assets"][0]["results"][0]["prompt"] == "Original click prompt"
    assert saved["assets"][0]["results"][0]["seed"] == 100
    assert calls == 2
