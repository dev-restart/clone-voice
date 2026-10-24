from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.api.deps import get_router
from app.config import Settings, get_settings
from app.main import app
from app.schemas import ContentItem, ContentResult, ModelCapabilities, PronunciationRule, RuntimeModelStatus
from app.services.content_store import ContentStore
from app.services.model_router import EngineOutput
from app.services.pronunciation import apply_pronunciations, preview_excerpt


def rule(source, replacement, language="ko"):
    return PronunciationRule(source=source, replacement=replacement, language=language)


@pytest.mark.parametrize(("text", "rules", "language", "expected"), [
    ("API를 AI로 MAIL API_v2 api", [rule("API", "에이피아이"), rule("AI", "에이아이")], "ko", "에이피아이를 에이아이로 MAIL API_v2 api"),
    ("Clone Voice와 Clone", [rule("Clone", "복제"), rule("Clone Voice", "클론보이스")], "ko", "클론보이스와 복제"),
    ("AI", [rule("AI", "인공지능", "all"), rule("AI", "에이아이", "ko")], "ko", "에이아이"),
    ("AI", [rule("AI", "에이아이")], "en", "AI"),
    ("API AI", [rule("API", "AI"), rule("AI", "인공지능")], "ko", "AI 인공지능"),
    ("[sigh] sigh C++", [rule("sigh", "한숨"), rule("C++", r"C\1")], "ko", r"[sigh] 한숨 C\1"),
    ("한글", [rule("한글", "한국어")], "ko", "한국어"),
])
def test_pronunciations_preserve_tags_words_languages_and_original_text(text, rules, language, expected):
    assert apply_pronunciations(text, rules, language) == expected


def test_preview_stops_at_a_sentence_and_caps_unbroken_text():
    assert preview_excerpt("첫 문장입니다. " + "두 번째 긴 문장 " * 30) == "첫 문장입니다."
    assert len(preview_excerpt("가" * 1000)) == 160


class RecordingAdapter:
    model_id = "voxcpm"
    label = "Test TTS"

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.calls = []

    def status(self):
        return RuntimeModelStatus(id=self.model_id, label=self.label, provider="test", status="available", enabled=True, capabilities=ModelCapabilities(tts=True, voice_clone_tts=True))

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        destination = self.output_dir / f"take-{len(self.calls)}.wav"
        destination.parent.mkdir(parents=True, exist_ok=True)
        t = np.arange(12000) / 24000
        sf.write(destination, 0.1 * np.sin(2 * np.pi * 220 * t), 24000)
        return EngineOutput(path=destination, duration_seconds=0.5)


@pytest.fixture
def studio(tmp_path):
    settings = Settings(storage_dir=tmp_path, voxcpm_enabled=False, soulx_singer_enabled=False, stable_audio_sfx_enabled=False)
    adapter = RecordingAdapter(settings.outputs_dir)

    class Router:
        def get(self, model_id, purpose="tts"):
            return adapter

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_router] = lambda: Router()
    with TestClient(app) as client:
        yield client, settings, adapter
    app.dependency_overrides.clear()


def create_project(client):
    response = client.post("/api/contents", json={
        "title": "브랜드 안내", "source_text": "API로 시작합니다.",
        "production_settings": {"model_id": "voxcpm", "speed": 1.2, "pronunciation_rules": [{"source": "API", "replacement": "에이피아이", "language": "ko"}]},
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_project_settings_survive_store_reopen_and_legacy_projects(studio):
    client, settings, _ = studio
    project = create_project(client)
    store = ContentStore(settings.contents_dir, settings)
    reopened = store.get(project["id"])
    assert reopened.production_settings.speed == 1.2
    assert reopened.production_settings.pronunciation_rules[0].replacement == "에이피아이"
    legacy = store.save(ContentItem(title="이전 대본", source_text="기존 데이터"))
    assert store.get(legacy.id).production_settings is None
    renamed = client.patch(f"/api/contents/{project['id']}", json={"title": "새 제목"})
    assert renamed.json()["production_settings"] == project["production_settings"]
    assert len(client.get("/api/contents").json()) == 2


def test_dictionary_rejects_duplicate_and_empty_entries_without_changing_saved_project(studio):
    client, _, _ = studio
    project = create_project(client)
    alias = {"source": "API", "replacement": "에이피아이"}
    for rules in [[alias, alias], [{"source": "  ", "replacement": "값"}], [{"source": "API", "replacement": "[tag]"}]]:
        response = client.patch(f"/api/contents/{project['id']}", json={"production_settings": {"pronunciation_rules": rules}})
        assert response.status_code == 422
    assert client.get("/api/contents").json()[0]["production_settings"] == project["production_settings"]


def test_preview_applies_aliases_uses_selected_settings_and_does_not_create_content(studio):
    client, _, adapter = studio
    source = "API로 시작합니다. " + "긴 문장을 이어갑니다. " * 40
    response = client.post("/api/tts/preview", json={
        "text": source, "model_id": "voxcpm", "language": "ko", "normalize_output": False,
        "num_step": 4, "pronunciation_rules": [{"source": "API", "replacement": "에이피아이"}],
    })
    assert response.status_code == 200, response.text
    assert adapter.calls[0]["text"].startswith("에이피아이로 시작합니다.")
    assert adapter.calls[0]["num_step"] == 4
    assert response.json()["text"].startswith("API로")
    assert len(response.json()["text"]) <= 160
    assert client.get("/api/contents").json() == []


def test_generation_and_export_keep_original_and_actual_spoken_script(studio):
    client, settings, adapter = studio
    project = create_project(client)
    response = client.post(f"/api/contents/{project['id']}/generate", json={"model_id": "voxcpm", "languages": ["ko"], "normalize_output": False, "speed": 1, "num_step": 4})
    assert response.status_code == 200, response.text
    assert adapter.calls[0]["text"] == "에이피아이로 시작합니다."
    result = response.json()["results"][0]
    assert result["text"] == "API로 시작합니다."
    assert result["spoken_text"] == "에이피아이로 시작합니다."
    assert result["production_settings"]["speed"] == 1
    assert result["production_settings"]["quality"] == "fast"
    # Later project edits must not rewrite a completed take's settings or script.
    client.patch(f"/api/contents/{project['id']}", json={"source_text": "새 대본", "production_settings": {"speed": 0.8}})
    export_url = f"/api/contents/{project['id']}/results/{result['id']}/export"
    archive_response = client.get(export_url, params={"format": "zip"})
    assert archive_response.status_code == 200
    with ZipFile(BytesIO(archive_response.content)) as archive:
        assert set(archive.namelist()) == {"audio.wav", "script.txt", "spoken-script.txt", "production.json"}
        assert archive.read("script.txt").decode() == "API로 시작합니다."
        assert archive.read("spoken-script.txt").decode() == "에이피아이로 시작합니다."
        assert json.loads(archive.read("production.json"))["production_settings"]["speed"] == 1
    mp3 = client.get(export_url, params={"format": "mp3"})
    assert mp3.status_code == 200 and len(mp3.content) > 100
    assert mp3.headers["content-type"] == "audio/mpeg"
    assert client.get(export_url, params={"format": "txt"}).text == "API로 시작합니다."
    assert client.get(export_url, params={"format": "exe"}).status_code == 422
    assert (settings.outputs_dir / "take-1.wav").exists()


def test_export_rejects_symlink_outside_outputs(studio, tmp_path):
    client, settings, _ = studio
    external = tmp_path / "private.txt"
    external.write_text("must not export")
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    (settings.outputs_dir / "outside.wav").symlink_to(external)
    result = ContentResult(language="ko", text="대본", audio_url="/api/files/outputs/outside.wav")
    content = ContentStore(settings.contents_dir, settings).save(ContentItem(title="경계 검사", source_text="대본", results=[result]))
    assert client.get(f"/api/contents/{content.id}/results/{result.id}/export").status_code == 404
