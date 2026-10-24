import pytest

from app.config import Settings
from app.schemas import VoiceProfile
from app.services.model_router import (
    CapabilityUnsupportedError,
    ModelRouter,
    ModelUnavailableError,
    Qwen3TTSAdapter,
)


def _voice(transcript: str | None) -> VoiceProfile:
    return VoiceProfile(name="v", transcript=transcript, audio_path="/tmp/ref.wav", audio_url="")


def test_qwen3_is_not_registered_by_default(tmp_path):
    router = ModelRouter(Settings(storage_dir=tmp_path))
    assert "qwen3-tts" not in router.adapters


def test_qwen3_disabled_by_default_and_refuses_to_generate(tmp_path):
    adapter = Qwen3TTSAdapter(Settings(storage_dir=tmp_path))
    assert adapter.status().status == "unavailable"
    with pytest.raises(ModelUnavailableError):
        adapter.generate(text="안녕하세요", voice=_voice("안녕하세요"))


def test_qwen3_requires_transcript_and_rejects_instruct(tmp_path):
    python = tmp_path / "python"
    python.write_text("")
    adapter = Qwen3TTSAdapter(
        Settings(storage_dir=tmp_path, qwen3_tts_enabled=True, qwen3_tts_python=str(python))
    )
    with pytest.raises(CapabilityUnsupportedError):
        adapter.generate(text="안녕하세요", voice=_voice(None))
    with pytest.raises(CapabilityUnsupportedError):
        adapter.generate(text="안녕하세요", voice=_voice("안녕하세요"), instruct="밝게")
