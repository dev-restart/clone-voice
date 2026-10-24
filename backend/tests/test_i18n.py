from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.i18n import current_locale, parse_accept_language, set_locale, reset_locale, tr
from app.main import app


def test_accept_language_picks_korean_or_english_and_defaults_to_korean():
    assert parse_accept_language("ko-KR,ko;q=0.9") == "ko"
    assert parse_accept_language("en-US,en;q=0.9,ko;q=0.5") == "en"
    assert parse_accept_language("fr-FR") == "ko"
    assert parse_accept_language(None) == "ko"
    assert parse_accept_language("") == "ko"


def test_tr_follows_the_context_locale():
    assert current_locale() == "ko"
    assert tr("안녕", "hello") == "안녕"
    token = set_locale("en")
    try:
        assert tr("안녕", "hello") == "hello"
    finally:
        reset_locale(token)
    assert tr("안녕", "hello") == "안녕"


def test_api_messages_follow_the_accept_language_header(tmp_path: Path):
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path, registered_models=["voxcpm"])
    try:
        client = TestClient(app)
        body = {"url": "https://example.com/watch?v=abc"}
        korean = client.post("/api/audio/media-info", json=body)
        english = client.post("/api/audio/media-info", json=body, headers={"Accept-Language": "en-US,en;q=0.9"})
    finally:
        app.dependency_overrides.clear()

    assert korean.status_code == english.status_code == 422
    assert "YouTube와 Instagram" in korean.json()["detail"]
    assert "Only single YouTube or Instagram video links" in english.json()["detail"]


def test_models_endpoint_localizes_the_recommendation_text(tmp_path: Path):
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path, registered_models=["voxcpm"])
    try:
        client = TestClient(app)
        english = client.get("/api/models", headers={"Accept-Language": "en"}).json()["models"][0]["recommended_for"]
        korean = client.get("/api/models").json()["models"][0]["recommended_for"]
    finally:
        app.dependency_overrides.clear()

    assert english[0] == "48kHz high-quality TTS"
    assert korean[0] == "48kHz 고품질 TTS"
