from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.schemas import ModelCapabilities, RuntimeModelStatus
from app.services.model_router import (
    ADAPTER_REGISTRY,
    BaseModelAdapter,
    ModelRouter,
    ModelUnavailableError,
    domains_for,
    register_adapter,
)


@register_adapter
class FakeMusicAdapter(BaseModelAdapter):
    model_id = "fake-music"
    label = "Fake Music"
    provider = "tests"
    install_command = "./download-models.sh --fake"

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(music_generation=True)

    def status(self) -> RuntimeModelStatus:
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            status="available",
            enabled=True,
            capabilities=self.capabilities,
        )


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def make_client(tmp_path: Path, **overrides) -> TestClient:
    settings = Settings(
        storage_dir=tmp_path,
        registered_models=["voxcpm", "soulx-singer", "stable-audio-sfx", "fake-music"],
        **overrides,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_decorated_adapter_is_registered_and_reports_its_domain(tmp_path: Path):
    assert ADAPTER_REGISTRY["fake-music"] is FakeMusicAdapter
    router = ModelRouter(Settings(storage_dir=tmp_path, registered_models=["fake-music", "voxcpm"]))

    models = {model.id: model for model in router.list()}

    assert models["fake-music"].domains == ["music"]
    assert models["voxcpm"].domains == ["voice"]
    assert models["fake-music"].install_command == "./download-models.sh --fake"


def test_domains_follow_capabilities():
    assert domains_for(ModelCapabilities(tts=True, voice_conversion=True)) == ["voice", "cover"]
    assert domains_for(ModelCapabilities(sound_effect_generation=True)) == ["sfx"]
    assert domains_for(ModelCapabilities()) == []


def test_router_picks_the_default_of_the_requested_purpose(tmp_path: Path):
    settings = Settings(
        storage_dir=tmp_path,
        registered_models=["voxcpm", "stable-audio-sfx", "fake-music"],
        default_music_model="fake-music",
    )
    router = ModelRouter(settings)

    assert router.get(None, purpose="sound_effect_generation").model_id == "stable-audio-sfx"
    assert router.get(None, purpose="music_generation").model_id == "fake-music"
    assert router.get(None, purpose="tts").model_id == "voxcpm"


def test_router_without_a_model_for_the_purpose_raises(tmp_path: Path):
    router = ModelRouter(Settings(storage_dir=tmp_path, registered_models=["voxcpm"]))

    with pytest.raises(ModelUnavailableError):
        router.get(None, purpose="music_generation")


def test_models_endpoint_returns_a_default_for_every_domain_with_models(tmp_path: Path):
    client = make_client(tmp_path)

    payload = client.get("/api/models").json()

    assert payload["default_models"] == {
        "voice": "voxcpm",
        "cover": "soulx-singer",
        "sfx": "stable-audio-sfx",
        "music": "fake-music",
    }


def test_default_models_can_be_saved_per_domain_and_survive_reload(tmp_path: Path):
    client = make_client(tmp_path)

    response = client.put(
        "/api/models/preferences",
        json={"default_models": {"music": "fake-music", "sfx": "stable-audio-sfx"}},
    )
    assert response.status_code == 200

    reloaded = make_client(tmp_path).get("/api/models").json()
    assert reloaded["default_models"]["music"] == "fake-music"


def test_default_model_must_belong_to_the_domain(tmp_path: Path):
    client = make_client(tmp_path)

    response = client.put("/api/models/preferences", json={"default_models": {"music": "voxcpm"}})

    assert response.status_code == 422
    assert "does not support" in response.json()["detail"]


def test_optional_domains_can_be_disabled_but_required_ones_cannot(tmp_path: Path):
    client = make_client(tmp_path)

    music_off = client.put(
        "/api/models/preferences",
        json={"model_preferences": {"fake-music": {"id": "fake-music", "enabled": False, "order": 1}}},
    )
    voice_off = client.put(
        "/api/models/preferences",
        json={"model_preferences": {"voxcpm": {"id": "voxcpm", "enabled": False, "order": 1}}},
    )

    assert music_off.status_code == 200
    assert "music" not in music_off.json()["default_models"]
    assert voice_off.status_code == 422
