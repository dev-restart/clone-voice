from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.production_assist import router
from app.config import Settings, get_settings
from app.services.ai_api_profiles import AiApiProfilesStore, ModelProfile, ProfileInput, RoutingInput
from app.services.production_assist_service import ProductionOutputError, parse_production_draft
from app.services.production_prompt_store import ProductionPromptStore, PromptUpdateRequest

COVER = {"quality": "balanced", "cfg_scale": 2.0, "pitch_shift": 0, "auto_shift": True, "separate_vocals": True, "mix_accompaniment": True}


def draft(kind):
    result = {"generation_prompt": "A soft piano motif with a gentle attack and clear ending", "lyrics": "", "structure": "", "advice": "명확한 시작과 끝을 두고 잔향을 절제하세요.", "settings": None}
    if kind in {"music", "song"}:
        result["structure"] = "짧은 도입 뒤 주제를 전개하고 후렴으로 마무리합니다."
    if kind == "song":
        result["lyrics"] = "오늘의 작은 빛을 따라\n다시 한 걸음 걸어가"
    if kind == "cover":
        result.update(generation_prompt="", structure="", settings={**COVER, "quality": "quality"})
        result["advice"] = "오디오를 듣지 않았으므로 음정은 유지합니다. 8단계는 시간이 더 걸릴 수 있습니다."
    return result


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


@pytest.fixture
def upstream():
    state = {"calls": [], "content": json.dumps(draft("sound_effect")), "status": 200}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["calls"].append((self.path, dict(self.headers), body))
            payload = {"choices": [{"message": {"content": state["content"]}, "finish_reason": "stop"}]}
            if state["status"] != 200:
                payload = {"error": "private-upstream-error fake-production-api-key"}
            encoded = json.dumps(payload).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


@pytest.fixture
def routed(settings, upstream):
    base, state = upstream
    store = AiApiProfilesStore(settings)
    profile = store.save(ProfileInput(
        name="Production API", base_url=base + "/v1", api_key="fake-production-api-key",
        credential_storage="private_file", models=[ModelProfile(id="production-model")],
    ))
    store.save_routing(RoutingInput(expected_revision=store.get()["revision"], sound_prompt={"provider_id": profile["id"], "model_id": "production-model"}))
    return profile, state


@pytest.mark.parametrize("kind", ["sound_effect", "music", "song", "cover"])
def test_saved_system_prompt_and_routed_model_reach_actual_http(client, settings, routed, kind):
    profile, state = routed
    state["content"] = json.dumps(draft(kind), ensure_ascii=False)
    custom = f"CUSTOM-{kind}: use a restrained and coherent arrangement."
    saved = client.put("/api/ai/production/prompts", json={"expected_revision": 0, "updates": {kind: custom}})
    assert saved.status_code == 200
    request = {"kind": kind, "brief": "차분한 분위기의 짧은 제작 초안"}
    if kind == "cover":
        request["current_settings"] = COVER
    response = client.post("/api/ai/production/assist", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["kind"] == kind and result["prompt_id"] == kind and result["prompt_revision"] == 1
    assert result["provider"] == profile["id"] and result["model"] == "production-model"
    assert len(state["calls"]) == 1
    path, headers, body = state["calls"][0]
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == "Bearer fake-production-api-key"
    assert body["model"] == "production-model"
    assert body["messages"][0]["role"] == "system"
    assert custom in body["messages"][0]["content"]
    assert "Application output contract" in body["messages"][0]["content"]
    assert "JSON input" in body["messages"][1]["content"]
    assert "fake-production-api-key" not in response.text
    assert "settings" in result
    if kind == "cover":
        assert result["settings"]["quality"] == "quality"
        assert result["settings"]["pitch_shift"] == COVER["pitch_shift"]


def test_restore_changes_next_actual_system_prompt(client, settings, routed):
    _, state = routed
    store = ProductionPromptStore(settings)
    store.update(PromptUpdateRequest(expected_revision=0, updates={"sound_effect": "CUSTOM-TO-REMOVE"}))
    assert client.post("/api/ai/production/assist", json={"kind": "sound_effect", "brief": "A short chime"}).status_code == 200
    client.put("/api/ai/production/prompts", json={"expected_revision": 1, "updates": {"sound_effect": None}})
    response = client.post("/api/ai/production/assist", json={"kind": "sound_effect", "brief": "A short chime"})
    assert response.status_code == 200
    assert response.json()["prompt_revision"] == 2
    assert "CUSTOM-TO-REMOVE" not in state["calls"][-1][2]["messages"][0]["content"]
    assert "event count" in state["calls"][-1][2]["messages"][0]["content"]


def test_provider_failure_is_explicit_and_does_not_echo_body(client, routed):
    _, state = routed
    state["status"] = 503
    response = client.post("/api/ai/production/assist", json={"kind": "music", "brief": "private-brief-marker"})
    assert response.status_code == 503
    assert len(state["calls"]) == 1
    for marker in ("private-upstream-error", "fake-production-api-key", "private-brief-marker"):
        assert marker not in response.text


def test_invalid_output_is_not_silently_replaced(client, routed):
    _, state = routed
    state["content"] = '{"generation_prompt": "private-output-marker"}'
    response = client.post("/api/ai/production/assist", json={"kind": "song", "brief": "가사 초안"})
    assert response.status_code == 503
    assert "private-output-marker" not in response.text
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("payload", [
    {"kind": "cover", "brief": "추천"},
    {"kind": "song", "brief": "노래", "current_settings": COVER},
    {"kind": "music", "brief": "  "},
    {"kind": "other", "brief": "private-marker"},
    {"kind": "music", "brief": "x" * 6001},
    {"kind": "cover", "brief": "추천", "current_settings": {**COVER, "pitch_shift": True}},
    {"kind": "cover", "brief": "추천", "current_settings": {**COVER, "auto_shift": "true"}},
    {"kind": "cover", "brief": "추천", "current_settings": {**COVER, "separate_vocals": False}},
])
def test_bad_request_never_calls_provider(client, routed, payload):
    _, state = routed
    response = client.post("/api/ai/production/assist", json=payload)
    assert response.status_code == 422
    assert "private-marker" not in response.text
    assert state["calls"] == []


@pytest.mark.parametrize("change", [
    {"cfg_scale": float("nan")}, {"cfg_scale": float("inf")}, {"cfg_scale": True},
    {"cfg_scale": "2.0"}, {"cfg_scale": 4.1}, {"cfg_scale": 0.4},
    {"pitch_shift": 25}, {"pitch_shift": True}, {"pitch_shift": 1.5},
    {"auto_shift": 1}, {"mix_accompaniment": "false"}, {"quality": "ultra"},
    {"steps": 32}, {"separate_vocals": False},
])
def test_cover_output_is_strict_and_finite(change):
    payload = draft("cover")
    payload["settings"].update(change)
    with pytest.raises(ProductionOutputError):
        parse_production_draft(json.dumps(payload), "cover")


@pytest.mark.parametrize("kind,change", [
    ("song", {"lyrics": ""}), ("music", {"structure": ""}),
    ("sound_effect", {"generation_prompt": "x" * 2001}),
    ("sound_effect", {"generation_prompt": "짧은 종소리"}),
    ("music", {"generation_prompt": "x" * 4001}),
    ("song", {"lyrics": "x" * 8001}), ("music", {"settings": COVER}),
    ("cover", {"generation_prompt": "unsupported prompt"}),
    ("sound_effect", {"lyrics": "unexpected singing"}),
    ("song", {"extra": "private-marker"}),
])
def test_invalid_or_incomplete_kind_output_is_rejected(kind, change):
    payload = draft(kind)
    payload.update(change)
    with pytest.raises(ProductionOutputError):
        parse_production_draft(json.dumps(payload), kind)


def test_json_fence_is_accepted_but_duplicate_keys_are_rejected():
    good = json.dumps(draft("sound_effect"))
    assert parse_production_draft("```json\n" + good + "\n```", "sound_effect").generation_prompt
    duplicate = good[:-1] + ', "advice": "duplicate"}'
    with pytest.raises(ProductionOutputError):
        parse_production_draft(duplicate, "sound_effect")
