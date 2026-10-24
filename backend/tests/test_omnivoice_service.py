from pathlib import Path

import numpy as np
import soundfile as sf

from app.config import Settings
from app.schemas import VoiceProfile
from app.services.omnivoice_service import OmniVoiceEngine


class DummyModel:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        return [np.zeros(24000, dtype=np.float32)]


def test_omnivoice_engine_uses_trimmed_reference_audio_tuple_for_saved_voice(tmp_path: Path):
    source = tmp_path / 'long.wav'
    t = np.linspace(0, 20, 20 * 24000, endpoint=False)
    waveform = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, 24000)

    settings = Settings(storage_dir=tmp_path, omnivoice_enabled=True)
    engine = OmniVoiceEngine(settings)
    dummy_model = DummyModel()
    engine._model = dummy_model

    voice = VoiceProfile(name='Long voice', audio_path=str(source), audio_url='/api/files/voices/long.wav')

    output_path, duration = engine.generate(text='테스트 문장입니다.', voice=voice)

    assert output_path.exists()
    assert duration == 1.0
    ref_audio = dummy_model.kwargs['ref_audio']
    assert isinstance(ref_audio, tuple)
    trimmed_waveform, sample_rate = ref_audio
    assert sample_rate == 24000
    assert len(trimmed_waveform) == 15 * 24000


def test_omnivoice_engine_keeps_transcript_for_short_reference(tmp_path: Path):
    source = tmp_path / 'short.wav'
    t = np.linspace(0, 4, 4 * 24000, endpoint=False)
    waveform = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, 24000)

    settings = Settings(storage_dir=tmp_path, omnivoice_enabled=True)
    engine = OmniVoiceEngine(settings)
    dummy_model = DummyModel()
    engine._model = dummy_model

    voice = VoiceProfile(
        name='Short voice',
        transcript='짧은 샘플의 정확한 대본입니다.',
        audio_path=str(source),
        audio_url='/api/files/voices/short.wav',
    )

    engine.generate(text='이 문장만 생성되어야 합니다.', voice=voice)

    assert dummy_model.kwargs['ref_text'] == '짧은 샘플의 정확한 대본입니다.'


def test_omnivoice_engine_uses_korean_language_hint_and_deterministic_decoding_for_korean_text(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path, omnivoice_enabled=True)
    engine = OmniVoiceEngine(settings)
    dummy_model = DummyModel()
    engine._model = dummy_model

    engine.generate(text='생성할 문안에 있는 말만 읽어 주세요.', num_step=16)

    assert dummy_model.kwargs['language'] == 'Korean'
    assert dummy_model.kwargs['position_temperature'] == 0.0
    assert dummy_model.kwargs['class_temperature'] == 0.0
    assert dummy_model.kwargs['preprocess_prompt'] is True


def test_omnivoice_engine_does_not_forward_stale_transcript_when_long_reference_was_condensed(tmp_path: Path):
    source = tmp_path / 'long.wav'
    t = np.linspace(0, 21, 21 * 24000, endpoint=False)
    waveform = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(source, waveform, 24000)

    settings = Settings(storage_dir=tmp_path, omnivoice_enabled=True)
    engine = OmniVoiceEngine(settings)
    dummy_model = DummyModel()
    engine._model = dummy_model

    voice = VoiceProfile(
        name='Long voice',
        transcript='이 문장은 원본 긴 샘플의 전체 대본입니다.',
        audio_path=str(source),
        audio_url='/api/files/voices/long.wav',
    )

    engine.generate(text='이 문장만 생성되어야 합니다.', voice=voice)

    assert 'ref_text' not in dummy_model.kwargs
