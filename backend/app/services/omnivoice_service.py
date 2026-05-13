import math
import re
import wave
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import Settings, get_settings
from app.schemas import ModelStatus, VoiceProfile
from app.services.audio_utils import REFERENCE_SAMPLE_RATE, prepare_reference_audio


_HANGUL_RE = re.compile(r"[가-힣]")
_SUPPORTED_ENGLISH_INSTRUCTS = {
    "american accent",
    "australian accent",
    "british accent",
    "canadian accent",
    "child",
    "chinese accent",
    "elderly",
    "female",
    "high pitch",
    "indian accent",
    "japanese accent",
    "korean accent",
    "low pitch",
    "male",
    "middle-aged",
    "moderate pitch",
    "portuguese accent",
    "russian accent",
    "teenager",
    "very high pitch",
    "very low pitch",
    "whisper",
    "young adult",
}
_KOREAN_TONE_TO_OMNIVOICE_INSTRUCT = {
    "차분하게": "low pitch",
    "조금 빠르게": None,
    "밝고 친근하게": "high pitch",
    "밝게": "high pitch",
    "신뢰감 있게": "middle-aged, moderate pitch",
    "화난 톤으로": "high pitch",
    "화난 톤": "high pitch",
    "슬픈 톤": "low pitch",
    "뉴스 앵커처럼": "middle-aged, moderate pitch",
}
_KOREAN_TONE_KEYWORD_RULES = [
    (("속삭", "whisper"), "whisper"),
    (("아이", "어린", "어린이", "아동"), "child, high pitch"),
    (("여성", "여자"), "female"),
    (("남성", "남자"), "male"),
    (("중년", "신뢰", "뉴스", "앵커"), "middle-aged, moderate pitch"),
    (("젊", "청년"), "young adult"),
    (("차분", "잔잔", "부드럽", "낮은", "저음", "슬픈"), "low pitch"),
    (("밝", "친근", "신나", "높은", "고음", "화난"), "high pitch"),
]
_LANGUAGE_CODE_TO_OMNIVOICE_LANGUAGE = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}
_LANGUAGE_CODE_TO_NATIVE_ACCENT = {
    "ko": "korean accent",
    "en": "american accent",
    "ja": "japanese accent",
    "zh": "chinese accent",
}
_ENGLISH_ACCENT_OVERRIDES = {
    "american accent",
    "british accent",
    "canadian accent",
    "australian accent",
    "indian accent",
}


def normalize_omnivoice_instruct(instruct: str | None) -> str | None:
    if not instruct or not instruct.strip():
        return None
    cleaned = instruct.strip()
    mapped = _KOREAN_TONE_TO_OMNIVOICE_INSTRUCT.get(cleaned)
    if cleaned in _KOREAN_TONE_TO_OMNIVOICE_INSTRUCT:
        return mapped
    english_items = [item.strip().lower() for item in cleaned.split(",") if item.strip()]
    if english_items and all(item in _SUPPORTED_ENGLISH_INSTRUCTS for item in english_items):
        return ", ".join(english_items)
    if _HANGUL_RE.search(cleaned):
        matched: list[str] = []
        for keywords, value in _KOREAN_TONE_KEYWORD_RULES:
            if any(keyword in cleaned for keyword in keywords):
                for item in value.split(","):
                    item = item.strip()
                    if item and item not in matched:
                        matched.append(item)
        return ", ".join(matched) if matched else None
    return None


def language_code_to_omnivoice_language(language_code: str | None) -> str | None:
    if not language_code:
        return None
    cleaned = language_code.strip().lower()
    if cleaned in _LANGUAGE_CODE_TO_OMNIVOICE_LANGUAGE:
        return _LANGUAGE_CODE_TO_OMNIVOICE_LANGUAGE[cleaned]
    for language_name in _LANGUAGE_CODE_TO_OMNIVOICE_LANGUAGE.values():
        if cleaned == language_name.lower():
            return language_name
    return None


def normalize_accent_override(accent: str | None, language_code: str | None) -> str | None:
    if not accent or not accent.strip():
        return None
    cleaned = accent.strip().lower()
    if cleaned not in _SUPPORTED_ENGLISH_INSTRUCTS or not cleaned.endswith(" accent"):
        return None
    language = (language_code or "").strip().lower()
    if language == "en" and cleaned in _ENGLISH_ACCENT_OVERRIDES:
        return cleaned
    return None


def effective_accent_for_language(language_code: str | None, accent: str | None = None) -> str | None:
    explicit_accent = normalize_accent_override(accent, language_code)
    if explicit_accent:
        return explicit_accent
    return _LANGUAGE_CODE_TO_NATIVE_ACCENT.get((language_code or "").strip().lower())


def combine_omnivoice_instruct(instruct: str | None, language_code: str | None, accent: str | None = None) -> str | None:
    safe_instruct = normalize_omnivoice_instruct(instruct)
    items = [item.strip() for item in safe_instruct.split(",") if item.strip()] if safe_instruct else []
    accent_hint = effective_accent_for_language(language_code, accent)
    if accent_hint:
        items = [item for item in items if not item.endswith(" accent")]
        items.append(accent_hint)
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return ", ".join(deduped) if deduped else None


def infer_generation_language(text: str, language_code: str | None = None) -> str | None:
    explicit_language = language_code_to_omnivoice_language(language_code)
    if explicit_language:
        return explicit_language
    if _HANGUL_RE.search(text):
        return "Korean"
    return None


class MockVoiceEngine:
    engine_name = "mock"

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir if output_dir.name == "outputs" else output_dir / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> ModelStatus:
        return ModelStatus(engine="mock", loaded=True, model_id=None, device="cpu")

    def preload(self) -> ModelStatus:
        return self.status()

    def generate(
        self,
        *,
        text: str,
        voice: VoiceProfile | None = None,
        instruct: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        duration: float | None = None,
        num_step: int = 32,
        guidance_scale: float = 2.0,
        denoise: bool = True,
        position_temperature: float = 0.0,
        class_temperature: float = 0.0,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
    ) -> tuple[Path, float]:
        del voice, instruct, language, num_step, guidance_scale, denoise, position_temperature, class_temperature, preprocess_prompt, postprocess_output, audio_chunk_duration, audio_chunk_threshold
        duration = duration or max(1.0, min(12.0, len(text) / 16 / speed))
        sample_rate = 24000
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        tone = 0.12 * np.sin(2 * math.pi * 220 * t) * np.exp(-t / max(duration, 1.0))
        output = self.output_dir / f"{uuid4().hex}.wav"
        sf.write(output, tone.astype(np.float32), sample_rate)
        return output, duration

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        del audio_path, language
        return "Transcribed speech placeholder"


class OmniVoiceEngine:
    engine_name = "omnivoice"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = settings.outputs_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._load_error: str | None = None

    def status(self) -> ModelStatus:
        return ModelStatus(
            engine="omnivoice",
            loaded=self._model is not None,
            model_id=self.settings.omnivoice_model_id,
            device=self._device_name(),
            error=self._load_error,
        )

    def preload(self) -> ModelStatus:
        self._ensure_model()
        return self.status()

    def generate(
        self,
        *,
        text: str,
        voice: VoiceProfile | None = None,
        instruct: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        duration: float | None = None,
        num_step: int = 32,
        guidance_scale: float = 2.0,
        denoise: bool = True,
        position_temperature: float = 0.0,
        class_temperature: float = 0.0,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
    ) -> tuple[Path, float | None]:
        model = self._ensure_model()
        kwargs: dict[str, object] = {
            "text": text,
            "speed": speed,
            "num_step": num_step,
            "guidance_scale": guidance_scale,
            "denoise": denoise,
            "position_temperature": position_temperature,
            "class_temperature": class_temperature,
            "preprocess_prompt": preprocess_prompt,
            "postprocess_output": postprocess_output,
            "audio_chunk_duration": audio_chunk_duration,
            "audio_chunk_threshold": audio_chunk_threshold,
        }
        if duration is not None:
            kwargs["duration"] = duration
        generation_language = infer_generation_language(text, language)
        if generation_language:
            kwargs["language"] = generation_language
        if voice is not None:
            prepared_reference = prepare_reference_audio(Path(voice.audio_path), REFERENCE_SAMPLE_RATE)
            kwargs["ref_audio"] = (prepared_reference.waveform, REFERENCE_SAMPLE_RATE)
            if voice.transcript and not prepared_reference.was_condensed:
                kwargs["ref_text"] = voice.transcript
        safe_instruct = normalize_omnivoice_instruct(instruct)
        if safe_instruct:
            kwargs["instruct"] = safe_instruct

        audio = model.generate(**kwargs)
        waveform = audio[0] if isinstance(audio, list) else audio
        output = self.output_dir / f"{uuid4().hex}.wav"
        sf.write(output, waveform, 24000)
        duration = float(len(waveform) / 24000) if hasattr(waveform, "__len__") else None
        return output, duration

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        del language
        self._ensure_model()
        try:
            import whisper
        except ImportError as exc:
            raise RuntimeError("Speech-to-text requires the optional 'openai-whisper' package or a custom ASR service.") from exc
        model = whisper.load_model("base")
        result = model.transcribe(str(audio_path))
        text = str(result.get("text", "")).strip()
        if not text:
            raise RuntimeError("No speech was detected in the recording.")
        return text

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            import torch
            from omnivoice import OmniVoice

            device = self._device_name(torch)
            dtype = self._dtype(torch, device)
            self._model = OmniVoice.from_pretrained(
                self.settings.omnivoice_model_id,
                device_map=device,
                dtype=dtype,
            )
            self._load_error = None
            return self._model
        except Exception as exc:  # model imports/downloads should be surfaced to the API/UI
            self._load_error = str(exc)
            raise

    def _device_name(self, torch_module=None) -> str:
        if self.settings.omnivoice_device != "auto":
            return self.settings.omnivoice_device
        if torch_module is None:
            try:
                import torch as torch_module
            except Exception:
                return "auto"
        if torch_module.cuda.is_available():
            return "cuda:0"
        if getattr(torch_module.backends, "mps", None) and torch_module.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _dtype(self, torch_module, device: str):
        if self.settings.omnivoice_dtype != "auto":
            return getattr(torch_module, self.settings.omnivoice_dtype)
        return torch_module.float16 if device.startswith("cuda") else torch_module.float32


@lru_cache(maxsize=1)
def get_voice_engine():
    settings = get_settings()
    if settings.omnivoice_enabled:
        return OmniVoiceEngine(settings)
    return MockVoiceEngine(settings.outputs_dir)
