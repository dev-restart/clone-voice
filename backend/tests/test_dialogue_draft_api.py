from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.schemas import DialogueDraftResponse, DialogueDraftSpeakers, DialogueDraftTurn
from app.api.routes import story as story_routes
from app.services.dialogue_draft_service import DialogueDraftFormatError, DialogueDraftGenerationError


def dialogue_draft_client(tmp_path: Path) -> TestClient:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(storage_dir=tmp_path)
    return TestClient(app)


def test_dialogue_draft_endpoint_returns_provider_and_model_metadata(tmp_path: Path, monkeypatch):
    client = dialogue_draft_client(tmp_path)

    def fake_generate(request, settings):
        assert request.format == "deep-dive"
        assert request.language == "en"
        assert request.speech_turns == 4
        return DialogueDraftResponse(
            title="Launch Review",
            summary="A concise deep dive on the launch memo.",
            format=request.format,
            language=request.language,
            speech_turns=request.speech_turns,
            include_sfx_cues=request.include_sfx_cues,
            speakers=DialogueDraftSpeakers(speaker_a="Host", speaker_b="Analyst"),
            turns=[
                DialogueDraftTurn(index=1, speaker="A", text="Let's start with the launch timeline."),
                DialogueDraftTurn(index=2, speaker="B", text="The memo says the delay came from QA."),
                DialogueDraftTurn(index=3, speaker="A", text="Was that the only factor?"),
                DialogueDraftTurn(index=4, speaker="B", text="No, supplier lead time also slipped."),
            ],
            provider="chatgpt",
            model="gpt-5.6-luna",
        )

    monkeypatch.setattr(story_routes, "generate_dialogue_draft", fake_generate)

    response = client.post(
        "/api/story-studio/dialogue-draft",
        json={
            "source_text": "Launch memo with QA and supplier delays, mitigation owners, and unresolved schedule risks.",
            "format": "deep-dive",
            "language": "en",
            "speech_turns": 4,
            "include_sfx_cues": False,
            "speaker_a_name": "Host",
            "speaker_b_name": "Analyst",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "chatgpt"
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["speakers"] == {"speaker_a": "Host", "speaker_b": "Analyst"}
    assert len(payload["turns"]) == 4


def test_dialogue_draft_endpoint_maps_generation_errors_to_503(tmp_path: Path, monkeypatch):
    client = dialogue_draft_client(tmp_path)
    monkeypatch.setattr(
        story_routes,
        "generate_dialogue_draft",
        lambda request, settings: (_ for _ in ()).throw(DialogueDraftGenerationError("upstream timeout")),
    )

    response = client.post(
        "/api/story-studio/dialogue-draft",
        json={
            "source_text": "제품 회의 메모에는 QA 지연과 공급 일정 위험이 적혀 있습니다.",
            "format": "interview",
            "language": "ko",
            "speech_turns": 4,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "upstream timeout"


def test_dialogue_draft_endpoint_maps_format_errors_to_422(tmp_path: Path, monkeypatch):
    client = dialogue_draft_client(tmp_path)
    monkeypatch.setattr(
        story_routes,
        "generate_dialogue_draft",
        lambda request, settings: (_ for _ in ()).throw(DialogueDraftFormatError("invalid JSON")),
    )

    response = client.post(
        "/api/story-studio/dialogue-draft",
        json={
            "source_text": "会议摘要提到测试延迟、供应时间风险以及待确认事项。",
            "format": "briefing",
            "language": "zh",
            "speech_turns": 4,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid JSON"


def test_dialogue_draft_endpoint_rejects_same_speaker_names(tmp_path: Path):
    client = dialogue_draft_client(tmp_path)

    response = client.post(
        "/api/story-studio/dialogue-draft",
        json={
            "source_text": "제품 회의 메모에는 QA 지연과 공급 일정 위험이 적혀 있습니다.",
            "format": "interview",
            "language": "ko",
            "speech_turns": 4,
            "speaker_a_name": "진행자",
            "speaker_b_name": "진행자",
        },
    )

    assert response.status_code == 422
    assert "서로 달라야" in response.text


def test_dialogue_draft_endpoint_rejects_source_shorter_than_twenty_characters_after_trim(tmp_path: Path):
    client = dialogue_draft_client(tmp_path)

    response = client.post(
        "/api/story-studio/dialogue-draft",
        json={
            "source_text": "  열여덟 자 미만의 짧은 자료입니다.  ",
            "format": "interview",
            "language": "ko",
            "speech_turns": 4,
        },
    )

    assert response.status_code == 422
    assert "20자 이상" in response.text
