from pathlib import Path

import pytest

from app import model_cache
from app.config import Settings


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, storage_dir=tmp_path / "storage", models_dir=tmp_path / "models", **overrides)


def make_snapshot(cache: Path, model_id: str) -> None:
    (cache / f"models--{model_id.replace('/', '--')}" / "snapshots" / "abc").mkdir(parents=True)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)


def test_new_install_downloads_into_the_project(tmp_path: Path):
    assert model_cache.resolve_voxcpm_cache_dir(make_settings(tmp_path)) == tmp_path / "models" / "huggingface"


def test_existing_global_cache_is_reused_instead_of_downloading_again(tmp_path: Path):
    settings = make_settings(tmp_path)
    make_snapshot(tmp_path / "home" / ".cache" / "huggingface" / "hub", settings.voxcpm_model_id)

    assert model_cache.resolve_voxcpm_cache_dir(settings) is None


def test_user_chosen_cache_dir_wins_and_counts_as_installed(tmp_path: Path, monkeypatch):
    mine = tmp_path / "mine"
    settings = make_settings(tmp_path, voxcpm_cache_dir=mine)
    make_snapshot(mine, settings.voxcpm_model_id)
    monkeypatch.setattr(model_cache.importlib.util, "find_spec", lambda name: object())

    assert model_cache.resolve_voxcpm_cache_dir(settings) == mine
    assert "voxcpm" not in model_cache.missing_models(settings)


def test_whisper_prefers_an_existing_global_download(tmp_path: Path):
    settings = make_settings(tmp_path)
    assert model_cache.whisper_download_root(settings) == str(tmp_path / "models" / "whisper")

    legacy = tmp_path / "home" / ".cache" / "whisper"
    legacy.mkdir(parents=True)
    (legacy / f"{settings.whisper_model}.pt").write_bytes(b"w")

    assert model_cache.whisper_download_root(settings) is None


def test_missing_models_reports_weights_that_are_not_downloaded(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(model_cache.importlib.util, "find_spec", lambda name: object())

    assert model_cache.missing_models(settings) == ["voxcpm", "whisper"]

    make_snapshot(tmp_path / "models" / "huggingface", settings.voxcpm_model_id)
    (tmp_path / "models" / "whisper").mkdir(parents=True)
    (tmp_path / "models" / "whisper" / f"{settings.whisper_model}.pt").write_bytes(b"w")

    assert model_cache.missing_models(settings) == []


def test_cover_and_sound_effect_models_are_reported_only_on_apple_silicon(tmp_path: Path, monkeypatch):
    settings = make_settings(tmp_path, soulx_singer_repo_dir=tmp_path / "vendor" / "soulx", stable_audio_repo_dir=tmp_path / "vendor" / "sa3")
    monkeypatch.setattr(model_cache.importlib.util, "find_spec", lambda name: object())

    monkeypatch.setattr(model_cache, "apple_silicon", lambda: False)
    assert model_cache.missing_optional_models(settings) == []

    monkeypatch.setattr(model_cache, "apple_silicon", lambda: True)
    monkeypatch.setattr("sys.platform", "darwin")
    assert model_cache.missing_optional_models(settings) == ["soulx-singer", "stable-audio-sfx"]
    assert "soulx-singer" in model_cache.missing_models(settings)
    assert "soulx-singer" not in model_cache.missing_models(settings, core_only=True)
