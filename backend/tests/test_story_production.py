from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.api.deps import get_router
from app.config import Settings, get_settings
from app.main import app
from app.schemas import DialogueDraftRequest, ModelCapabilities, RuntimeModelStatus
from app.services.dialogue_draft_service import DialogueDraftFormatError, build_dialogue_draft_prompt, parse_dialogue_draft_response
from app.services.model_router import EngineOutput
from app.services.progress import progress_events
from app.services.story_project_store import StoryProjectStore


class Adapter:
    model_id = "voxcpm"
    label = "Test synthesis"

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.calls = []

    def status(self):
        return RuntimeModelStatus(id=self.model_id, label=self.label, provider="test", status="available", enabled=True, capabilities=ModelCapabilities(tts=True, voice_clone_tts=True, sound_effect_generation=True))

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        path = self.output_dir / f"take-{uuid4().hex}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, 0.1 * np.sin(2 * np.pi * 220 * np.arange(12000) / 24000), 24000)
        return EngineOutput(path=path, duration_seconds=0.5)

    generate_sound_effect = generate


@pytest.fixture
def studio(tmp_path):
    settings = Settings(storage_dir=tmp_path)
    adapter = Adapter(settings.outputs_dir)

    class Router:
        def get(self, model_id, purpose="tts"):
            return adapter

    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_router] = lambda: Router()
    with TestClient(app) as client:
        yield client, settings, adapter
    app.dependency_overrides.clear()


def project_payload():
    return {
        "id": uuid4().hex, "title": "대담 제작 확인", "revision": 0,
        "source_text": "자료에는 출시 일정 변경과 점검에 필요한 근거가 있습니다.",
        "segments": [
            {"id": "line-a", "text": "자료에서 확인된 사실부터 살펴봅시다.", "speaker_name": "진행자", "speed": 1, "pause_after_ms": 300},
            {"id": "line-b", "text": "아직 확정하지 못한 일정은 구분하겠습니다.", "speaker_name": "분석가", "speed": 1, "pause_after_ms": 200},
        ],
    }


def test_first_browser_requests_can_initialize_a_fresh_database_concurrently(tmp_path):
    settings = Settings(storage_dir=tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(lambda _: StoryProjectStore(settings).list(), range(6))) == [[]] * 6


def create(client, payload=None):
    payload = payload or project_payload()
    response = client.put(f"/api/story-studio/projects/{payload['id']}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def generate(client, project, **kwargs):
    response = client.post("/api/story-studio/generate", json={
        "project_id": project["id"], "title": project["title"], "segments": project["segments"],
        "normalize_output": False, **kwargs,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_project_survives_store_reopen_and_accepts_unfinished_drafts(studio):
    client, settings, _ = studio
    payload = project_payload()
    payload["segments"][0]["text"] = ""
    payload["segments"][1]["translated_text"] = "An unfinished schedule."
    saved = create(client, payload)
    reopened = StoryProjectStore(settings).get(saved["id"])
    assert reopened.segments[0].text == ""
    assert reopened.segments[1].translated_text == "An unfinished schedule."
    assert reopened.source_text == payload["source_text"]
    assert client.get("/api/story-studio/projects").json()[0]["revision"] == 1


def test_old_browser_cannot_overwrite_or_delete_newer_project(studio):
    client, _, _ = studio
    saved = create(client)
    updated = {**saved, "title": "새 브라우저에서 수정한 제목"}
    assert client.put(f"/api/story-studio/projects/{saved['id']}", json=updated).json()["revision"] == 2
    assert client.put(f"/api/story-studio/projects/{saved['id']}", json=saved).status_code == 409
    assert client.delete(f"/api/story-studio/projects/{saved['id']}?revision=1").status_code == 409
    assert client.get(f"/api/story-studio/projects/{saved['id']}").json()["title"] == updated["title"]


def test_project_id_and_duplicate_segment_ids_are_validated(studio):
    client, _, _ = studio
    payload = project_payload()
    assert client.put("/api/story-studio/projects/different", json=payload).status_code == 422
    payload["segments"][1]["id"] = payload["segments"][0]["id"]
    assert client.put(f"/api/story-studio/projects/{payload['id']}", json=payload).status_code == 422


def test_generation_is_saved_without_browser_callback_and_assets_are_identified(studio):
    client, settings, adapter = studio
    project = create(client)
    result = generate(client, project)
    reopened = StoryProjectStore(settings).get(project["id"])
    assert reopened.result.audio_url == result["audio_url"]
    assert reopened.revision == 2
    assert len(adapter.calls) == 2
    assert result["source_segments"][0]["speaker_name"] == "진행자"
    assert sf.info(settings.outputs_dir / Path(result["audio_url"]).name).duration == pytest.approx(1.5)
    assets = client.get("/api/assets").json()["generated_files"]
    assert next(asset for asset in assets if asset["audio_url"] == result["audio_url"])["kind"] == "dialogue"


def test_result_save_preserves_newer_editor_changes(studio):
    client, settings, _ = studio
    project = create(client)
    result = generate(client, project)
    latest = client.get(f"/api/story-studio/projects/{project['id']}").json()
    latest["segments"][0]["text"] = "수정한 현재 대본"
    saved = create(client, latest)
    store = StoryProjectStore(settings)
    store.save_result(project["id"], store.get(project["id"]).result)
    reopened = store.get(project["id"])
    assert reopened.segments[0].text == saved["segments"][0]["text"]
    assert reopened.result.source_segments[0].text == result["source_segments"][0]["text"]


def test_later_missing_voice_fails_before_any_inference_and_finishes_progress(studio):
    client, _, adapter = studio
    payload = project_payload()
    payload["segments"][1]["voice_id"] = "missing-voice"
    progress_id = uuid4().hex
    response = client.post("/api/story-studio/generate", json={"segments": payload["segments"], "progress_id": progress_id})
    assert response.status_code == 404
    assert not adapter.calls
    assert progress_events.pop(progress_id)["done"] is True


def test_eighty_one_segments_are_rejected_instead_of_silently_truncated(studio):
    client, _, adapter = studio
    response = client.post("/api/story-studio/generate", json={"segments": [{"id": str(i), "text": "단락"} for i in range(81)]})
    assert response.status_code == 422
    assert not adapter.calls


def test_package_uses_generated_script_even_after_editor_changes(studio):
    client, _, _ = studio
    project = create(client)
    generated = generate(client, project)
    current = client.get(f"/api/story-studio/projects/{project['id']}").json()
    current["segments"][0]["text"] = "나중에 수정한 대사"
    create(client, current)
    package = client.get(f"/api/story-studio/projects/{project['id']}/export?format=zip")
    assert package.status_code == 200
    with ZipFile(BytesIO(package.content)) as archive:
        assert "나중에 수정한 대사" not in archive.read("script.txt").decode()
        assert generated["segments"][0]["text"] in archive.read("script.txt").decode()
        assert "00:00:00,800 --> 00:00:01,300" in archive.read("captions.srt").decode()
        assert json.loads(archive.read("project.json"))["segments"][0]["text"] == "나중에 수정한 대사"
        assert archive.read("source.txt").decode() == current["source_text"]
        assert sf.info(BytesIO(archive.read("audio.wav"))).duration == pytest.approx(1.5)


def test_subtitles_account_for_effects_and_pauses(studio):
    client, _, _ = studio
    payload = project_payload()
    payload["segments"].insert(1, {"id": "effect", "text": "short click", "segment_type": "sfx", "pause_after_ms": 100})
    project = create(client, payload)
    generate(client, project)
    response = client.get(f"/api/story-studio/projects/{project['id']}/export?format=srt")
    assert "00:00:01,400 --> 00:00:01,900" in response.text
    assert "short click" not in response.text
    assert "분석가:" in response.text


@pytest.mark.parametrize("format", ["wav", "mp3", "txt", "srt"])
def test_export_formats_are_valid_and_downloadable(studio, format):
    client, _, _ = studio
    project = create(client)
    generate(client, project)
    response = client.get(f"/api/story-studio/projects/{project['id']}/export?format={format}")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    if format in {"wav", "mp3"}:
        assert sf.info(BytesIO(response.content)).duration > 1
    else:
        assert "진행자:" in response.text


def test_draft_backup_and_deleted_project_keep_existing_audio(studio):
    client, settings, _ = studio
    project = create(client)
    assert client.get(f"/api/story-studio/projects/{project['id']}/export?format=json").json()["source_text"] == project["source_text"]
    assert client.get(f"/api/story-studio/projects/{project['id']}/export?format=zip").status_code == 409
    result = generate(client, project)
    assert client.delete(f"/api/story-studio/projects/{project['id']}?revision=2").status_code == 204
    assert (settings.outputs_dir / Path(result["audio_url"]).name).is_file()
    assert client.get(f"/api/story-studio/projects/{project['id']}").status_code == 404


def test_export_does_not_read_symlink_outside_outputs(studio, tmp_path):
    client, settings, _ = studio
    project = create(client)
    result = generate(client, project)
    audio_path = settings.outputs_dir / Path(result["audio_url"]).name
    external = tmp_path / "outside.wav"
    audio_path.rename(external)
    audio_path.symlink_to(external)
    assert client.get(f"/api/story-studio/projects/{project['id']}/export?format=wav").status_code == 404


def test_four_speaker_draft_is_grounded_and_every_speaker_must_appear():
    request = DialogueDraftRequest(source_text="회의 기록에 출시 일정 조정과 품질 검증 결과가 자세히 나와 있습니다.", speech_turns=4, speaker_a_name="진행자", speaker_b_name="게스트", speaker_c_name="분석가", speaker_d_name="해설자")
    payload = {"title": "출시 점검", "summary": "자료에 근거한 대담", "turns": [{"speaker": speaker, "text": f"{speaker} 대사"} for speaker in ["진행자", "게스트", "분석가", "해설자"]]}
    result = parse_dialogue_draft_response(json.dumps(payload, ensure_ascii=False), request, provider="local", model="test")
    assert [turn.speaker for turn in result.turns] == ["A", "B", "C", "D"]
    assert result.additional_speakers == {"C": "분석가", "D": "해설자"}
    prompt = build_dialogue_draft_prompt(request)
    assert "4-speaker" in prompt and "Speaker D" in prompt and "source only" in prompt
    payload["turns"][-1]["speaker"] = "게스트"
    with pytest.raises(DialogueDraftFormatError, match="모든 화자"):
        parse_dialogue_draft_response(json.dumps(payload), request, provider="local", model="test")


@pytest.mark.parametrize("names", [{"speaker_c_name": "A"}, {"speaker_a_name": "B"}, {"speaker_c_name": "Guest B"}])
def test_display_name_cannot_be_miscast_as_another_speaker(names):
    with pytest.raises(ValueError, match="다른 화자"):
        DialogueDraftRequest(source_text="등록 목소리를 서로 다른 역할에 정확하게 배정하는 검증용 원문입니다.", **names)
