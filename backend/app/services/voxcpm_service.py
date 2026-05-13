from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import Settings
from app.schemas import ModelStatus, VoiceProfile

VOXCPM_SAMPLE_RATE = 48000
_OMNIVOICE_DEFAULT_STEPS = 32

_KOREAN_CONTROL_PROMPTS = {
    "차분하게": "calm and steady tone",
    "조금 빠르게": "slightly faster pace",
    "밝고 친근하게": "warm and friendly tone",
    "밝게": "bright tone",
    "이쁘게": "pretty and charming tone",
    "예쁘게": "pretty and charming tone",
    "섹시하게": "soft and alluring tone",
    "신뢰감 있게": "confident and trustworthy tone",
    "화난 톤으로": "angry tone",
    "화난 톤": "angry tone",
    "슬픈 톤": "sad and low tone",
    "저음으로": "low pitch",
    "뉴스 앵커처럼": "news anchor style",
}


def _split_control_prompt(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;/]+", value) if item.strip()]


def _normalize_control_prompt(value: str) -> list[str]:
    parts = _split_control_prompt(value)
    if not parts:
        return []
    return [_KOREAN_CONTROL_PROMPTS.get(part, part) for part in parts]


def build_voxcpm_control_prompt(
    *,
    style_prompt: str | None = None,
    tone_prompt: str | None = None,
    instruct: str | None = None,
    language: str | None = None,
    accent: str | None = None,
    speed: float | None = None,
) -> str | None:
    prompts: list[str] = []
    for value in (style_prompt, tone_prompt, instruct):
        if value and value.strip():
            prompts.extend(_normalize_control_prompt(value.strip()))

    if accent and accent.strip():
        prompts.append(accent.strip())
    elif language and language.strip().lower() == "ko":
        prompts.append("natural Korean pronunciation")

    if speed is not None:
        if speed >= 1.15:
            prompts.append("slightly faster pace")
        elif speed <= 0.85:
            prompts.append("slightly slower pace")

    deduped: list[str] = []
    seen: set[str] = set()
    for prompt in prompts:
        key = prompt.lower()
        if key not in seen:
            deduped.append(prompt)
            seen.add(key)
    return ", ".join(deduped) if deduped else None


def normalize_voxcpm_target_text(text: str) -> str:
    normalized = re.sub(r"\r\n?", "\n", text.strip())
    if not normalized:
        return ""

    pieces = re.split(r"(\n+)", normalized)
    output: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        if set(piece) == {"\n"}:
            if output:
                previous = output[-1].rstrip()
                if previous and not re.search(r"[.!?。！？…~]$", previous):
                    previous += "."
                output[-1] = previous
            output.append(" ... " if len(piece) >= 2 else " ")
            continue
        output.append(piece.strip())

    return re.sub(r"[ \t]+", " ", "".join(output)).strip()


def apply_voxcpm_control_prefix(text: str, instruct: str | None) -> str:
    target_text = normalize_voxcpm_target_text(text)
    control = re.sub(r"\s+", " ", instruct or "").strip()
    return f"({control}){target_text}" if control else target_text


class VoxCPMEngine:
    engine_name = "voxcpm"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = settings.outputs_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._load_error: str | None = None

    def status(self) -> ModelStatus:
        return ModelStatus(
            engine=self.engine_name,
            loaded=self._model is not None,
            model_id=self.settings.voxcpm_model_id,
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
        num_step: int = _OMNIVOICE_DEFAULT_STEPS,
        guidance_scale: float = 2.0,
        denoise: bool = False,
        position_temperature: float = 0.0,
        class_temperature: float = 0.0,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
    ) -> tuple[Path, float | None]:
        del duration, position_temperature, class_temperature, postprocess_output, audio_chunk_duration, audio_chunk_threshold
        model = self._ensure_model()
        # VoxCPM exposes the target utterance as a single `text` argument. Do not
        # accept a separate control-prompt parameter. Its CLI applies style
        # control by prefixing `(control instruction)` to the target text, so the
        # adapter mirrors that behavior instead of dropping tone/style metadata.
        control_prompt = instruct
        del language, speed
        kwargs: dict[str, object] = {
            "text": apply_voxcpm_control_prefix(text, control_prompt),
            "cfg_value": guidance_scale,
            "inference_timesteps": self._inference_timesteps(num_step),
            "max_len": self.settings.voxcpm_max_len,
            "normalize": preprocess_prompt,
            "denoise": denoise,
        }

        if voice is not None:
            reference_path = str(Path(voice.audio_path).resolve())
            kwargs["reference_wav_path"] = reference_path
            if voice.transcript:
                kwargs["prompt_wav_path"] = reference_path
                kwargs["prompt_text"] = voice.transcript

        audio = model.generate(**kwargs)
        waveform = np.asarray(audio, dtype=np.float32)
        sample_rate = self._sample_rate(model)
        output = self.output_dir / f"{uuid4().hex}.wav"
        sf.write(output, waveform, sample_rate)
        duration_seconds = float(len(waveform) / sample_rate) if hasattr(waveform, "__len__") else None
        return output, duration_seconds

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from voxcpm import VoxCPM

            self._model = VoxCPM.from_pretrained(
                self.settings.voxcpm_model_id,
                load_denoiser=self.settings.voxcpm_load_denoiser,
                cache_dir=str(self.settings.voxcpm_cache_dir) if self.settings.voxcpm_cache_dir else None,
                local_files_only=self.settings.voxcpm_local_files_only,
                optimize=self.settings.voxcpm_optimize,
                device=self._device_name(),
            )
            self._load_error = None
            return self._model
        except Exception as exc:
            self._load_error = str(exc)
            raise

    def _device_name(self) -> str:
        if self.settings.voxcpm_device != "auto":
            return self.settings.voxcpm_device
        try:
            import torch
        except Exception:
            return "auto"
        if torch.cuda.is_available():
            return "cuda:0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _inference_timesteps(self, num_step: int | None) -> int:
        if num_step and int(num_step) != _OMNIVOICE_DEFAULT_STEPS:
            return max(1, int(num_step))
        return self.settings.voxcpm_inference_timesteps

    def _sample_rate(self, model) -> int:
        tts_model = getattr(model, "tts_model", None)
        sample_rate = getattr(tts_model, "sample_rate", None)
        return int(sample_rate or VOXCPM_SAMPLE_RATE)
