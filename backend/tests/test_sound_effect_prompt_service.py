import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services import sound_effect_prompt_service as service


def test_extract_explicit_duration_supports_korean_and_english():
    assert service.extract_explicit_duration("2.4초 동안 울리는 짧은 알림음") == 2.5
    assert service.extract_explicit_duration("A soft alarm for 7 seconds") == 7.0


def test_duration_fallback_distinguishes_one_shot_and_ambience():
    assert service.infer_sound_effect_duration("나무 문이 한 번 닫히는 소리") == 2.0
    assert service.infer_sound_effect_duration("밤 도심의 잔잔한 거리 배경음") == 8.0


def test_plan_uses_local_llm_translation_and_keeps_explicit_duration(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path)

    monkeypatch.setattr(
        service,
        "request_sound_effect_plan",
        lambda prompt, settings, fixed_duration=None: (
            "A heavy iron door slams once in a quiet hallway, dry studio recording",
            6.0,
            "local",
            "translategemma:12b",
        ),
    )

    plan = service.plan_sound_effect_prompt(
        "조용한 복도에서 무거운 철문이 한 번 닫히는 소리, 2초",
        settings,
        auto_duration=True,
    )

    assert plan.generation_prompt.startswith("A heavy iron door")
    assert plan.duration_seconds == 2.0
    assert plan.duration_mode == "auto"
    assert plan.translated is True
    assert plan.planner == "local-llm"
    assert plan.provider == "local"
    assert plan.model == "translategemma:12b"


def test_parse_sound_effect_plan_accepts_json_wrapped_in_text():
    content = "result: " + json.dumps(
        {"generation_prompt": "A short glass impact, close microphone", "duration_seconds": "1.2"}
    )

    prompt, duration = service.parse_sound_effect_plan(content)

    assert prompt == "A short glass impact, close microphone"
    assert duration == 1.0


def test_known_effect_type_duration_takes_priority_over_llm_guess(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path)
    monkeypatch.setattr(
        service,
        "request_sound_effect_plan",
        lambda *args, **kwargs: ("Distant city traffic at night, field recording", 1.0, "chatgpt", "gpt-5.6-luna"),
    )

    plan = service.plan_sound_effect_prompt("밤 도심의 잔잔한 거리 배경음", settings, auto_duration=True)

    assert plan.duration_seconds == 8.0


def test_plan_falls_back_to_rules_when_local_llm_is_unavailable(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path)
    monkeypatch.setattr(
        service,
        "request_sound_effect_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    plan = service.plan_sound_effect_prompt("나무 문이 닫히는 소리", settings, auto_duration=True)

    assert plan.duration_seconds == 2.0
    assert plan.planner == "rules-fallback"

@pytest.mark.parametrize("duration", [True, False, float("nan"), float("inf"), -float("inf"), "NaN", "Infinity", 10 ** 400])
def test_nonfinite_or_boolean_ai_duration_is_rejected(duration):
    content = json.dumps({"generation_prompt": "A short dry chime", "duration_seconds": duration})
    with pytest.raises(RuntimeError):
        service.parse_sound_effect_plan(content)


def test_stored_sound_prompt_is_used_for_automatic_planning(tmp_path, monkeypatch):
    from app.services.production_prompt_store import ProductionPromptStore, PromptUpdateRequest
    settings = Settings(_env_file=None, storage_dir=tmp_path, ai_text_settings_path=tmp_path / "selection.json")
    ProductionPromptStore(settings).update(PromptUpdateRequest(expected_revision=0, updates={"sound_effect": "CUSTOM-SFX: emphasize natural decay."}))
    observed = []
    class Provider:
        def __init__(self, *args, **kwargs):
            pass
        def complete(self, prompt, **kwargs):
            observed.append((prompt, kwargs))
            return SimpleNamespace(content=json.dumps({"generation_prompt": "A short bell with natural decay", "duration_seconds": 2}), provider="api-test", model="sound-model")
    monkeypatch.setattr(service, "AiTextProviderService", Provider)
    plan = service.plan_sound_effect_prompt("짧은 종소리, 2초", settings)
    assert plan.planner == "api-llm"
    assert plan.generation_prompt == "A short bell with natural decay"
    assert plan.duration_seconds == 2.0
    assert observed[0][1]["task"] == "sound_prompt"
    assert "CUSTOM-SFX: emphasize natural decay." in observed[0][1]["system_prompt"]
    assert "Application output contract" in observed[0][1]["system_prompt"]


def test_invalid_ai_duration_uses_existing_rule_fallback(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, storage_dir=tmp_path, ai_text_settings_path=tmp_path / "selection.json")
    class Provider:
        def __init__(self, *args, **kwargs):
            pass
        def complete(self, *args, **kwargs):
            return SimpleNamespace(content='{"generation_prompt":"A door slam","duration_seconds":NaN}', provider="api-test", model="sound-model")
    monkeypatch.setattr(service, "AiTextProviderService", Provider)
    plan = service.plan_sound_effect_prompt("문이 닫히는 소리", settings)
    assert plan.planner == "rules-fallback"
    assert plan.duration_seconds == 2.0
    assert plan.provider is None
