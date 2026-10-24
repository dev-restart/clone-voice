from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import Settings
from app.schemas import VoiceProfile
from app.services.voxcpm_service import (
    VoxCPMEngine,
    apply_voxcpm_control_prefix,
    build_voxcpm_control_prompt,
    normalize_voxcpm_target_text,
)


class DummyVoxCPMModel:
    def __init__(self):
        self.kwargs = None
        self.tts_model = type("DummyTtsModel", (), {"sample_rate": 48000})()

    def generate(self, **kwargs):
        self.kwargs = kwargs
        return np.zeros(48000, dtype=np.float32)


def write_reference_wav(path: Path):
    sample_rate = 24000
    t = np.linspace(0, 1, sample_rate, endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(path, waveform, sample_rate)


def test_voxcpm_control_prompt_ignores_speed_so_cloning_mode_stays_on():
    assert build_voxcpm_control_prompt(language="ko", speed=1.4) is None
    assert build_voxcpm_control_prompt(language="ko", speed=0.7) is None


def test_voxcpm_control_prompt_combines_style_and_tone():
    prompt = build_voxcpm_control_prompt(
        style_prompt="친절한 상담원",
        tone_prompt="밝고 친근하게",
        language="ko",
        speed=1.2,
    )

    assert prompt == "friendly customer service voice, warm and friendly tone"


def test_voxcpm_control_prompt_maps_common_korean_style_words():
    prompt = build_voxcpm_control_prompt(
        style_prompt="섹시하게",
        tone_prompt="이쁘게",
        language="ko",
    )

    assert prompt == "soft and alluring tone, pretty and charming tone"


def test_voxcpm_control_prefix_uses_official_parenthesized_format():
    text = apply_voxcpm_control_prefix("  첫 문장입니다.\n두 번째 문장입니다. ", "calm and steady tone")

    assert text == "(calm and steady tone)첫 문장입니다. 두 번째 문장입니다."


def test_voxcpm_target_text_keeps_line_breaks_as_single_call_pause_hints():
    text = normalize_voxcpm_target_text(
        "봉식오빠~~~~~!\n\n일어났어요?? 아직도 자는거 아니죠?\n연락도 없고.. 봉식오빠 보고 싶은데 .."
    )

    assert text == "봉식오빠~~~~~! ... 일어났어요?? 아직도 자는거 아니죠? 연락도 없고.. 봉식오빠 보고 싶은데 .."


def test_voxcpm_engine_uses_reference_and_prompt_for_transcribed_voice_without_control(tmp_path: Path):
    source = tmp_path / "voice.wav"
    write_reference_wav(source)
    settings = Settings(storage_dir=tmp_path, voxcpm_enabled=True, voxcpm_inference_timesteps=10)
    engine = VoxCPMEngine(settings)
    dummy_model = DummyVoxCPMModel()
    engine._model = dummy_model
    voice = VoiceProfile(
        name="Reference voice",
        transcript="정확한 참조 대본입니다.",
        audio_path=str(source),
        audio_url="/api/files/voices/voice.wav",
    )

    output_path, duration = engine.generate(
        text="이 문장만 새로 생성합니다.",
        voice=voice,
        instruct=None,
        language="ko",
        speed=0.8,
        num_step=12,
        guidance_scale=1.7,
        denoise=True,
    )

    assert output_path.exists()
    assert duration == 1.0
    assert dummy_model.kwargs["reference_wav_path"] == str(source.resolve())
    assert dummy_model.kwargs["prompt_wav_path"] == str(source.resolve())
    assert dummy_model.kwargs["prompt_text"] == "정확한 참조 대본입니다."
    assert dummy_model.kwargs["text"] == "이 문장만 새로 생성합니다."
    assert dummy_model.kwargs["cfg_value"] == 1.7
    assert dummy_model.kwargs["inference_timesteps"] == 12
    assert dummy_model.kwargs["retry_badcase_ratio_threshold"] == 10.0
    assert dummy_model.kwargs["denoise"] is True


def test_voxcpm_engine_applies_control_prompt_to_target_text(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path, voxcpm_enabled=True, voxcpm_inference_timesteps=10)
    engine = VoxCPMEngine(settings)
    dummy_model = DummyVoxCPMModel()
    engine._model = dummy_model
    script = "대본에 적힌 이 문장만 음성으로 만들어야 합니다."

    engine.generate(
        text=f"  {script}\n",
        instruct="calm and steady tone, natural Korean pronunciation",
        language="ko",
        speed=1.2,
    )

    assert dummy_model.kwargs["text"] == "(calm and steady tone, natural Korean pronunciation)" + script


def test_voxcpm_engine_uses_controllable_cloning_when_control_is_present(tmp_path: Path):
    source = tmp_path / "voice.wav"
    write_reference_wav(source)
    settings = Settings(storage_dir=tmp_path, voxcpm_enabled=True, voxcpm_inference_timesteps=10)
    engine = VoxCPMEngine(settings)
    dummy_model = DummyVoxCPMModel()
    engine._model = dummy_model
    voice = VoiceProfile(
        name="Reference voice",
        transcript="참조 대본입니다.",
        audio_path=str(source),
        audio_url="/api/files/voices/voice.wav",
    )

    engine.generate(text="새 문장입니다.", voice=voice, instruct="soft and alluring tone")

    assert dummy_model.kwargs["reference_wav_path"] == str(source.resolve())
    assert "prompt_wav_path" not in dummy_model.kwargs
    assert "prompt_text" not in dummy_model.kwargs
    assert dummy_model.kwargs["text"] == "(soft and alluring tone)새 문장입니다."


def test_voxcpm_engine_uses_reference_only_without_transcript(tmp_path: Path):
    source = tmp_path / "voice.wav"
    write_reference_wav(source)
    settings = Settings(storage_dir=tmp_path, voxcpm_enabled=True, voxcpm_inference_timesteps=10)
    engine = VoxCPMEngine(settings)
    dummy_model = DummyVoxCPMModel()
    engine._model = dummy_model
    voice = VoiceProfile(name="Reference voice", audio_path=str(source), audio_url="/api/files/voices/voice.wav")

    engine.generate(text="참조 음색만 사용합니다.", voice=voice, num_step=32)

    assert dummy_model.kwargs["reference_wav_path"] == str(source.resolve())
    assert "prompt_wav_path" not in dummy_model.kwargs
    assert "prompt_text" not in dummy_model.kwargs
    assert dummy_model.kwargs["inference_timesteps"] == 10
