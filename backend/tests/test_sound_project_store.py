from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas import SoundEffectResult
from app.services import sound_project_store as service
from app.services.sound_project_store import SoundAsset, SoundProject, SoundProjectConflict, SoundProjectNotFound, SoundProjectStore


@pytest.fixture
def sound_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, storage_dir=tmp_path)


@pytest.fixture
def sound_store(sound_settings: Settings) -> SoundProjectStore:
    return SoundProjectStore(sound_settings)


def draft(project_id: str = "project-1") -> SoundProject:
    return SoundProject(
        id=project_id,
        title="게임 효과음",
        category="game",
        assets=[SoundAsset(id="asset-1", title="확인 버튼", category="ui", prompt="A short soft wooden click")],
    )


def result(result_id: str = "result-1", prompt: str = "A short soft wooden click") -> SoundEffectResult:
    return SoundEffectResult(
        id=result_id,
        prompt=prompt,
        generation_prompt="A short soft wooden click, no speech, no music",
        negative_prompt="speech, music",
        audio_url=f"/api/files/outputs/{result_id}.wav",
        duration_seconds=1.5,
        seed=123,
    )


def edited(project: SoundProject, **updates: object) -> SoundProject:
    return SoundProject.model_validate({**project.model_dump(mode="python"), **updates})


def test_create_read_update_and_reload_are_persistent(sound_store: SoundProjectStore, sound_settings: Settings) -> None:
    saved = sound_store.save("project-1", draft())
    assert saved.revision == 1
    assert SoundProjectStore(sound_settings).get(saved.id) == saved
    assert sound_store.list() == [saved]

    changed = sound_store.save(saved.id, edited(saved, title="영상 효과음", category="video"))
    assert changed.revision == 2
    assert changed.title == "영상 효과음"
    assert changed.created_at == saved.created_at
    assert changed.updated_at >= saved.updated_at
    assert changed.assets[0].created_at == saved.assets[0].created_at
    assert changed.assets[0].updated_at == saved.assets[0].updated_at
    assert SoundProjectStore(sound_settings).get(saved.id) == changed


def test_stale_edits_cannot_overwrite_newer_data(sound_store: SoundProjectStore) -> None:
    saved = sound_store.save("project-1", draft())
    latest = sound_store.save(saved.id, edited(saved, title="최신 이름"))
    with pytest.raises(SoundProjectConflict):
        sound_store.save(saved.id, edited(saved, title="이전 화면에서 수정"))
    assert sound_store.get(saved.id) == latest
    with pytest.raises(SoundProjectConflict):
        sound_store.save(saved.id, draft())


def test_deleted_project_is_not_resurrected_by_stale_save(sound_store: SoundProjectStore) -> None:
    saved = sound_store.save("project-1", draft())
    sound_store.delete(saved.id, saved.revision)
    with pytest.raises(SoundProjectNotFound):
        sound_store.save(saved.id, edited(saved, title="삭제 후 늦게 저장"))
    assert sound_store.list() == []


def test_delete_is_revision_guarded_and_keeps_output_files(sound_store: SoundProjectStore, sound_settings: Settings) -> None:
    output = Path(sound_settings.storage_dir) / "outputs" / "result-1.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"existing generated media")
    saved = sound_store.save("project-1", draft())
    updated = sound_store.save_result(saved.id, "asset-1", [result()])
    with pytest.raises(SoundProjectConflict):
        sound_store.delete(saved.id, saved.revision)
    assert sound_store.get(saved.id) == updated
    sound_store.delete(updated.id, updated.revision)
    assert output.read_bytes() == b"existing generated media"
    with pytest.raises(SoundProjectNotFound):
        sound_store.get(updated.id)


def test_generation_preserves_current_draft_and_original_result_prompt(sound_store: SoundProjectStore) -> None:
    saved = sound_store.save("project-1", draft())
    asset = saved.assets[0].model_dump(mode="python")
    asset.update(prompt="A bright metallic click", title="다음에 만들 소리")
    edited_draft = sound_store.save(saved.id, edited(saved, assets=[asset]))
    completed = sound_store.save_result(saved.id, "asset-1", [result(prompt="Original generation prompt")])
    assert completed.revision == edited_draft.revision + 1
    assert completed.assets[0].prompt == "A bright metallic click"
    assert completed.assets[0].title == "다음에 만들 소리"
    assert completed.assets[0].results[0].prompt == "Original generation prompt"
    assert sound_store.save_result(saved.id, "asset-1", [result()]) == completed


def test_existing_result_snapshots_are_immutable_but_removable(sound_store: SoundProjectStore) -> None:
    saved = sound_store.save("project-1", draft())
    completed = sound_store.save_result(saved.id, "asset-1", [result(prompt="Original")])
    asset = completed.assets[0].model_dump(mode="python")
    asset["prompt"] = "New draft"
    asset["results"][0]["prompt"] = "Accidental overwrite"
    asset["results"][0]["audio_url"] = "/api/files/outputs/wrong.wav"
    updated = sound_store.save(saved.id, edited(completed, assets=[asset]))
    assert updated.assets[0].prompt == "New draft"
    assert updated.assets[0].results[0].prompt == "Original"
    assert updated.assets[0].results[0].audio_url == "/api/files/outputs/result-1.wav"
    removed = sound_store.save(saved.id, edited(updated, assets=[{**asset, "results": []}]))
    assert removed.assets[0].results == []


def test_parallel_generations_append_without_losing_results(
    sound_store: SoundProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_store.save("project-1", draft())
    barrier = Barrier(2)
    real_replace = service._replace_if_revision

    def replace_together(project: SoundProject, expected_revision: int, *, settings: Settings) -> bool:
        if expected_revision == 1:
            barrier.wait(timeout=5)
        return real_replace(project, expected_revision, settings=settings)

    monkeypatch.setattr(service, "_replace_if_revision", replace_together)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(sound_store.save_result, "project-1", "asset-1", [result(f"result-{index}")]) for index in (1, 2)]
        for future in futures:
            future.result(timeout=10)
    saved = sound_store.get("project-1")
    assert saved.revision == 3
    assert {item.id for item in saved.assets[0].results} == {"result-1", "result-2"}


def test_result_retry_keeps_an_edit_that_won_the_first_cas(
    sound_store: SoundProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_store.save("project-1", draft())
    real_replace = service._replace_if_revision
    first = True

    def edit_before_result(project: SoundProject, expected_revision: int, *, settings: Settings) -> bool:
        nonlocal first
        if first:
            first = False
            latest = sound_store.get(project.id)
            asset = latest.assets[0].model_dump(mode="python")
            asset["prompt"] = "Edited while generation was running"
            sound_store.save(latest.id, edited(latest, assets=[asset]))
        return real_replace(project, expected_revision, settings=settings)

    monkeypatch.setattr(service, "_replace_if_revision", edit_before_result)
    saved = sound_store.save_result("project-1", "asset-1", [result()])
    assert saved.revision == 3
    assert saved.assets[0].prompt == "Edited while generation was running"
    assert saved.assets[0].results[0].prompt == "A short soft wooden click"


def test_removed_asset_does_not_reappear_on_generation_completion(sound_store: SoundProjectStore) -> None:
    saved = sound_store.save("project-1", draft())
    without_asset = sound_store.save(saved.id, edited(saved, assets=[]))
    with pytest.raises(SoundProjectConflict, match="파일은 결과 라이브러리"):
        sound_store.save_result(saved.id, "asset-1", [result()])
    assert sound_store.get(saved.id) == without_asset


def test_project_deleted_between_read_and_result_cas_stays_deleted(
    sound_store: SoundProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_store.save("project-1", draft())

    def remove_before_result(project: SoundProject, expected_revision: int, *, settings: Settings) -> bool:
        sound_store.delete(project.id, expected_revision)
        return False

    monkeypatch.setattr(service, "_replace_if_revision", remove_before_result)
    with pytest.raises(SoundProjectConflict, match="파일은 결과 라이브러리"):
        sound_store.save_result("project-1", "asset-1", [result()])
    assert sound_store.list() == []


def test_failed_result_cas_is_bounded_to_three_attempts(
    sound_store: SoundProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = sound_store.save("project-1", draft())
    calls: list[int] = []

    def always_conflicting(project: SoundProject, expected_revision: int, *, settings: Settings) -> bool:
        calls.append(expected_revision)
        return False

    monkeypatch.setattr(service, "_replace_if_revision", always_conflicting)
    with pytest.raises(SoundProjectConflict, match="파일은 결과 라이브러리"):
        sound_store.save_result("project-1", "asset-1", [result()])
    assert len(calls) == 3
    assert sound_store.get("project-1") == original


def test_full_history_is_not_silently_truncated(sound_store: SoundProjectStore) -> None:
    project = draft()
    project.assets[0].results = [result(f"result-{index}") for index in range(100)]
    saved = sound_store.save(project.id, project)
    with pytest.raises(SoundProjectConflict, match="100개"):
        sound_store.save_result(saved.id, "asset-1", [result("extra-result")])
    assert len(sound_store.get(saved.id).assets[0].results) == 100


@pytest.mark.parametrize("project_id", ["", "../outside", "a/b", "a\\b", "x" * 81, "한글-id"])
def test_project_id_boundaries(project_id: str) -> None:
    with pytest.raises(ValidationError):
        SoundProject(id=project_id, title="프로젝트")


@pytest.mark.parametrize(
    "updates",
    [
        {"title": "   "},
        {"category": "music"},
        {"duration_seconds": 0.49},
        {"duration_seconds": 15.01},
        {"duration_seconds": float("nan")},
        {"guidance_scale": float("inf")},
        {"guidance_scale": 8.01},
        {"variations": 0},
        {"variations": 5},
        {"seed": -1},
        {"seed": 2147483644},
        {"seed": True},
        {"prompt": "x" * 2001},
        {"negative_prompt": "x" * 1001},
    ],
)
def test_asset_schema_boundaries(updates: dict) -> None:
    with pytest.raises(ValidationError):
        SoundAsset.model_validate({"id": "asset-1", "title": "사운드", **updates})


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/audio.wav",
        "/api/files/uploads/source.wav",
        "/api/files/outputs/../secret.wav",
        "/api/files/outputs/a/b.wav",
        "/api/files/outputs/a%2fb.wav",
        "/api/files/outputs/a.wav?download=1",
        "/api/files/outputs/a.wav#fragment",
        "/api/files/outputs/.hidden",
        "/api/files/outputs/a\\b.wav",
    ],
)
def test_imported_results_only_reference_safe_local_output_urls(url: str) -> None:
    item = result().model_dump(mode="python")
    item["audio_url"] = url
    with pytest.raises(ValidationError):
        SoundAsset(id="asset-1", title="사운드", results=[item])


def test_duplicate_ids_and_collection_limits_are_rejected() -> None:
    asset = SoundAsset(id="asset-1", title="사운드")
    with pytest.raises(ValidationError):
        SoundProject(id="project-1", title="프로젝트", assets=[asset, asset])
    with pytest.raises(ValidationError):
        SoundProject(id="project-1", title="프로젝트", assets=[asset.model_copy(update={"id": f"asset-{index}"}) for index in range(301)])
    with pytest.raises(ValidationError):
        SoundAsset(id="asset-1", title="사운드", results=[result(), result()])
    with pytest.raises(ValidationError):
        SoundAsset(id="asset-1", title="사운드", results=[result(f"result-{index}") for index in range(101)])


def test_legacy_import_does_not_require_current_media_files(sound_store: SoundProjectStore) -> None:
    project = draft()
    project.assets[0].results = [result("legacy-result")]
    saved = sound_store.save(project.id, project)
    assert saved.assets[0].results[0].audio_url == "/api/files/outputs/legacy-result.wav"


def test_path_and_body_id_must_agree(sound_store: SoundProjectStore) -> None:
    with pytest.raises(ValueError, match="ID"):
        sound_store.save("different-id", draft())
    assert sound_store.list() == []


def test_http_contract_and_export(sound_settings: Settings) -> None:
    from app.api.routes.sound_projects import router

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_settings] = lambda: sound_settings
    with TestClient(application) as client:
        created = client.put("/api/sound-projects/project-1", json=draft().model_dump(mode="json"))
        assert created.status_code == 200
        body = created.json()
        assert body["revision"] == 1
        assert client.get("/api/sound-projects").json() == {"projects": [body]}
        assert client.get("/api/sound-projects/project-1").json() == body
        exported = client.get("/api/sound-projects/project-1/export")
        assert exported.status_code == 200
        assert exported.json() == body
        assert "attachment" in exported.headers["content-disposition"]
        assert client.put("/api/sound-projects/project-1", json=draft().model_dump(mode="json")).status_code == 409
        assert client.delete("/api/sound-projects/project-1?revision=2").status_code == 409
        assert client.delete("/api/sound-projects/project-1?revision=1").status_code == 204
        assert client.get("/api/sound-projects/project-1").status_code == 404
        mismatch = client.put("/api/sound-projects/different-id", json=draft().model_dump(mode="json"))
        assert mismatch.status_code == 422
