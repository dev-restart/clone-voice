from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import Settings, get_settings
from app.i18n import tr
from app.schemas import MODEL_DOMAINS, ModelCapabilities, ModelDomain, RuntimeModelStatus, VoiceProfile
from app.services.audio_utils import REFERENCE_SAMPLE_RATE
from app.services.cosyvoice_service import COSYVOICE_SAMPLE_RATE, CosyVoiceEngine
from app.services.omnivoice_service import OmniVoiceEngine
from app.services.stable_audio_service import STABLE_AUDIO_SAMPLE_RATE, StableAudioSfxEngine
from app.services.voxcpm_service import VOXCPM_SAMPLE_RATE, VoxCPMEngine


logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    pass


class CapabilityUnsupportedError(RuntimeError):
    pass


# capability flag on ModelCapabilities -> the studio area that lists the model
DOMAIN_CAPABILITY: dict[ModelDomain, str] = {
    "voice": "tts",
    "music": "music_generation",
    "cover": "voice_conversion",
    "sfx": "sound_effect_generation",
}
# router.get(purpose=...) -> domain
PURPOSE_DOMAIN: dict[str, ModelDomain] = {
    "tts": "voice",
    "music_generation": "music",
    "voice_conversion": "cover",
    "sound_effect_generation": "sfx",
}


def domains_for(capabilities: ModelCapabilities) -> list[ModelDomain]:
    return [domain for domain in MODEL_DOMAINS if getattr(capabilities, DOMAIN_CAPABILITY[domain], False)]


# Adding a model: subclass BaseModelAdapter in any module that is imported here and decorate it with
# @register_adapter. The id then becomes valid in CLONE_VOICE_REGISTERED_MODELS. See docs/adding-a-model.md.
ADAPTER_REGISTRY: dict[str, type["BaseModelAdapter"]] = {}


def register_adapter(adapter_class: type["BaseModelAdapter"]) -> type["BaseModelAdapter"]:
    ADAPTER_REGISTRY[adapter_class.model_id] = adapter_class
    return adapter_class


@dataclass(frozen=True)
class EngineOutput:
    path: Path
    duration_seconds: float | None
    transcript: str | None = None


def _duration_for_waveform(waveform, sample_rate: int) -> float | None:
    return float(len(waveform) / sample_rate) if hasattr(waveform, "__len__") else None


def _write_model_audio(output_dir: Path, audio, sample_rate: int = REFERENCE_SAMPLE_RATE) -> EngineOutput:
    output_dir.mkdir(parents=True, exist_ok=True)
    waveform = audio[0] if isinstance(audio, list) else audio
    if isinstance(waveform, tuple):
        waveform = waveform[0]
    waveform = np.asarray(waveform, dtype=np.float32)
    output = output_dir / f"{uuid4().hex}.wav"
    sf.write(output, waveform, sample_rate)
    return EngineOutput(path=output, duration_seconds=_duration_for_waveform(waveform, sample_rate))


class BaseModelAdapter:
    model_id: str
    label: str
    provider: str
    sample_rate: int = REFERENCE_SAMPLE_RATE
    # Shown on the model card in Settings. All optional.
    homepage: str | None = None
    license: str | None = None
    platforms: tuple[str, ...] = ()
    install_command: str | None = None

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    @property
    def recommended_for(self) -> list[str]:
        return []

    def status(self) -> RuntimeModelStatus:
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=False,
            loaded=False,
            status="unavailable",
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message="Adapter is not configured.",
        )

    def preload(self) -> RuntimeModelStatus:
        return self.status()

    def generate(self, **kwargs) -> EngineOutput:
        raise CapabilityUnsupportedError(f"{self.label} does not support TTS generation.")

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        raise CapabilityUnsupportedError(f"{self.label} does not support STT.")

    def convert_voice(self, source_audio: Path, target_voice: VoiceProfile | None, **kwargs) -> EngineOutput:
        raise CapabilityUnsupportedError(f"{self.label} does not support voice conversion.")

    def generate_sound_effect(self, **kwargs) -> EngineOutput:
        raise CapabilityUnsupportedError(f"{self.label} does not support sound-effect generation.")

@register_adapter
class OmniVoiceAdapter(BaseModelAdapter):
    model_id = "omnivoice"
    label = "OmniVoice"
    provider = "k2-fsa"
    homepage = "https://github.com/k2-fsa/OmniVoice"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = OmniVoiceEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True, voice_clone_tts=True, voice_design=True, stt=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["초고속 추론", "다국어 TTS", "등록 목소리 복제"], ["Ultra-fast inference", "Multilingual TTS", "Clones registered voices"])

    def status(self) -> RuntimeModelStatus:
        engine_status = self.engine.status()
        if not self.settings.omnivoice_enabled:
            status = "unavailable"
            message = "Disabled by CLONE_VOICE_OMNIVOICE_ENABLED=false."
        elif engine_status.error:
            status = "unavailable"
            message = engine_status.error
        else:
            status = "available"
            message = None
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.omnivoice_enabled,
            loaded=engine_status.loaded,
            model_id=engine_status.model_id,
            device=engine_status.device,
            status=status,
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=message,
        )

    def preload(self) -> RuntimeModelStatus:
        if not self.settings.omnivoice_enabled:
            return self.status()
        try:
            self.engine.preload()
        except Exception as exc:
            return self.status().model_copy(update={"status": "unavailable", "message": str(exc)})
        return self.status()

    def generate(self, **kwargs) -> EngineOutput:
        if not self.settings.omnivoice_enabled:
            raise ModelUnavailableError("CLONE_VOICE_OMNIVOICE_ENABLED is false.")
        path, duration = self.engine.generate(**kwargs)
        return EngineOutput(path=path, duration_seconds=duration)

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        if not self.settings.omnivoice_enabled:
            raise ModelUnavailableError("CLONE_VOICE_OMNIVOICE_ENABLED is false.")
        return self.engine.transcribe(audio_path, language=language)


@register_adapter
class VoxCPMAdapter(BaseModelAdapter):
    model_id = "voxcpm"
    label = "VoxCPM2"
    provider = "OpenBMB"
    homepage = "https://github.com/OpenBMB/VoxCPM"
    license = "Apache-2.0"
    platforms = ("macOS", "Linux")
    install_command = "./download-models.sh --tts"
    sample_rate = VOXCPM_SAMPLE_RATE

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = VoxCPMEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True, voice_clone_tts=True, voice_design=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["48kHz 고품질 TTS", "한국어 포함 30개 언어", "스타일 제어 음성 복제"], ["48kHz high-quality TTS", "30 languages incl. Korean", "Style-controlled voice cloning"])

    def status(self) -> RuntimeModelStatus:
        engine_status = self.engine.status()
        if not self.settings.voxcpm_enabled:
            status = "unavailable"
            message = "Disabled by CLONE_VOICE_VOXCPM_ENABLED=false."
        elif engine_status.error:
            status = "unavailable"
            message = engine_status.error
        else:
            status = "available"
            message = None
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.voxcpm_enabled,
            loaded=engine_status.loaded,
            model_id=engine_status.model_id,
            device=engine_status.device,
            status=status,
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=message,
        )

    def preload(self) -> RuntimeModelStatus:
        if not self.settings.voxcpm_enabled:
            return self.status()
        try:
            self.engine.preload()
        except Exception as exc:
            return self.status().model_copy(update={"status": "unavailable", "message": str(exc)})
        return self.status()

    def generate(self, **kwargs) -> EngineOutput:
        if not self.settings.voxcpm_enabled:
            raise ModelUnavailableError("CLONE_VOICE_VOXCPM_ENABLED is false.")
        path, duration = self.engine.generate(**kwargs)
        return EngineOutput(path=path, duration_seconds=duration)


_QWEN3_LANGUAGES = {
    "ko": "Korean", "kr": "Korean", "korean": "Korean", "한국어": "Korean",
    "en": "English", "english": "English",
    "ja": "Japanese", "jp": "Japanese", "japanese": "Japanese",
    "zh": "Chinese", "chinese": "Chinese",
}


@register_adapter
class Qwen3TTSAdapter(BaseModelAdapter):
    """EXPERIMENTAL, disabled by default. Qwen3-TTS Base voice cloning in a separate venv.

    Not in DEFAULT_REGISTERED_MODELS: enable with CLONE_VOICE_QWEN3_TTS_ENABLED=true, add "qwen3-tts" to
    CLONE_VOICE_REGISTERED_MODELS and point CLONE_VOICE_QWEN3_TTS_PYTHON at a venv with ``qwen-tts``.
    Only the transcript-based clone path is exposed (no style/speed control, so ``instruct`` is rejected).
    Each call reloads the model through scripts/run_qwen3_tts.py; a persistent worker is needed before
    this could serve interactive use, and that is only worth building if the blind test favours it.
    """

    model_id = "qwen3-tts"
    label = "Qwen3-TTS (experimental)"
    provider = "Alibaba Qwen"
    sample_rate = 24000

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True, voice_clone_tts=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["실험용", "참조 음성 + 대본 복제", "별도 Python 환경 필요"], ["Experimental", "Reference voice + script cloning", "Needs a separate Python environment"])

    @property
    def runner_script(self) -> Path:
        return Path(__file__).resolve().parents[2] / "scripts/run_qwen3_tts.py"

    def _configuration_error(self) -> str | None:
        if not self.settings.qwen3_tts_enabled:
            return "Disabled by CLONE_VOICE_QWEN3_TTS_ENABLED=false."
        python = self.settings.qwen3_tts_python
        if not python or not Path(python).expanduser().exists():
            return "Set CLONE_VOICE_QWEN3_TTS_PYTHON to a venv python that has `qwen-tts` installed."
        return None

    def status(self) -> RuntimeModelStatus:
        error = self._configuration_error()
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.qwen3_tts_enabled,
            loaded=False,
            model_id=self.settings.qwen3_tts_model_id,
            device=self.settings.qwen3_tts_device,
            status="unavailable" if error else "available",
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=error,
        )

    def generate(self, **kwargs) -> EngineOutput:
        error = self._configuration_error()
        if error:
            raise ModelUnavailableError(error)
        voice: VoiceProfile | None = kwargs.get("voice")
        if voice is None or not voice.audio_path or not (voice.transcript or "").strip():
            raise CapabilityUnsupportedError("Qwen3-TTS needs a registered voice with a sample transcript.")
        if kwargs.get("instruct"):
            raise CapabilityUnsupportedError("Qwen3-TTS Base does not support style instructions.")
        language = _QWEN3_LANGUAGES.get(str(kwargs.get("language") or "ko").strip().lower(), "Korean")
        output_dir = self.settings.outputs_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{uuid4().hex}.wav"
        command = [
            str(Path(self.settings.qwen3_tts_python).expanduser()),
            str(self.runner_script),
            "--model-id", self.settings.qwen3_tts_model_id,
            "--device", self.settings.qwen3_tts_device,
            "--dtype", self.settings.qwen3_tts_dtype,
            "--ref-audio", str(Path(voice.audio_path).resolve()),
            "--ref-text", voice.transcript.strip(),
            "--text", " ".join(str(kwargs["text"]).split()),
            "--language", language,
            "--output", str(output),
        ]
        cache_dir = self.settings.qwen3_tts_cache_dir or self.settings.voxcpm_cache_dir
        if cache_dir:
            command += ["--cache-dir", str(Path(cache_dir).resolve())]
        if self.settings.qwen3_tts_local_files_only:
            command.append("--local-files-only")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.settings.qwen3_tts_timeout_seconds,
                check=False,
                env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Qwen3-TTS exceeded {self.settings.qwen3_tts_timeout_seconds}s.") from exc
        if completed.returncode != 0 or not output.exists():
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            raise RuntimeError((detail or "Qwen3-TTS failed.")[-2000:])
        info = sf.info(output)
        return EngineOutput(path=output, duration_seconds=float(info.frames / info.samplerate))


@register_adapter
class CosyVoiceAdapter(BaseModelAdapter):
    model_id = "cosyvoice"
    label = "CosyVoice"
    provider = "FunAudioLLM"
    sample_rate = COSYVOICE_SAMPLE_RATE

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = CosyVoiceEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        has_default_voice = bool(self.settings.cosyvoice_default_spk_id or self.settings.cosyvoice_prompt_wav)
        return ModelCapabilities(tts=True, voice_clone_tts=True, voice_design=has_default_voice)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["다국어 zero-shot TTS", "등록 목소리 복제", "CosyVoice2/3 교체 가능", "별도 Python 3.10 런타임"], ["Multilingual zero-shot TTS", "Clones registered voices", "CosyVoice 2/3 swappable", "Separate Python 3.10 runtime"])

    def status(self) -> RuntimeModelStatus:
        engine_status = self.engine.status()
        if not self.settings.cosyvoice_enabled:
            status = "unavailable"
            message = "Disabled by CLONE_VOICE_COSYVOICE_ENABLED=false."
        elif engine_status.error:
            status = "unavailable"
            message = engine_status.error
        else:
            status = "available"
            message = None
            has_dedicated_python = bool(self.settings.cosyvoice_python) or (self.engine.repo_dir / ".venv" / "bin" / "python").exists()
            if not has_dedicated_python and sys.version_info[:2] != (3, 10):
                message = "CosyVoice upstream recommends Python 3.10; set CLONE_VOICE_COSYVOICE_PYTHON to a dedicated CosyVoice venv."
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.cosyvoice_enabled,
            loaded=engine_status.loaded,
            model_id=engine_status.model_id,
            device=engine_status.device,
            status=status,
            sample_rate=self.settings.cosyvoice_sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=message,
        )

    def preload(self) -> RuntimeModelStatus:
        if not self.settings.cosyvoice_enabled:
            return self.status()
        try:
            self.engine.preload()
        except Exception as exc:
            return self.status().model_copy(update={"loaded": False, "status": "unavailable", "message": str(exc)})
        return self.status()

    def generate(self, **kwargs) -> EngineOutput:
        if not self.settings.cosyvoice_enabled:
            raise ModelUnavailableError("CLONE_VOICE_COSYVOICE_ENABLED is false.")
        path, duration = self.engine.generate(**kwargs)
        return EngineOutput(path=path, duration_seconds=duration)


@register_adapter
class SoulXSingerAdapter(BaseModelAdapter):
    model_id = "soulx-singer"
    label = "SoulX-Singer"
    provider = "Soul-AILab / MLX community"
    homepage = "https://github.com/Soul-AILab/SoulX-Singer"
    license = "Apache-2.0"
    platforms = ("macOS (Apple Silicon)",)
    install_command = "./download-models.sh --soulx-singer"
    sample_rate = 24000

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(voice_conversion=True, singing_voice_conversion=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["AI 노래 커버", "zero-shot SVC", "보컬/반주 자동 분리", "Apple Silicon MPS"], ["AI song covers", "Zero-shot SVC", "Automatic vocal/accompaniment separation", "Apple Silicon MPS"])

    @property
    def repo_dir(self) -> Path:
        return self.settings.soulx_singer_repo_dir.resolve()

    @property
    def runner_script(self) -> Path:
        return Path(__file__).resolve().parents[2] / "scripts/run_soulx_singer.py"

    @property
    def model_dir(self) -> Path:
        path = self.settings.soulx_singer_model_dir
        return path.resolve() if path.is_absolute() else (self.repo_dir / path).resolve()

    @property
    def preprocess_model_dir(self) -> Path:
        path = self.settings.soulx_singer_preprocess_model_dir
        return path.resolve() if path.is_absolute() else (self.repo_dir / path).resolve()

    @property
    def whisper_model_dir(self) -> Path:
        path = self.settings.soulx_singer_whisper_model_dir
        return path.resolve() if path.is_absolute() else (self.repo_dir / path).resolve()

    @property
    def python_executable(self) -> str:
        if self.settings.soulx_singer_python:
            configured = Path(self.settings.soulx_singer_python).expanduser()
            if not configured.is_absolute():
                configured = Path(__file__).resolve().parents[2] / configured
            return str(configured.absolute())
        local_python = self.repo_dir / ".venv" / "bin" / "python"
        if local_python.exists():
            return str(local_python)
        return sys.executable

    @property
    def local_python(self) -> Path:
        return self.repo_dir / ".venv" / "bin" / "python"

    def status(self) -> RuntimeModelStatus:
        message = None
        state = "unavailable"
        loaded = False
        if not self.settings.soulx_singer_enabled:
            message = tr("SoulX-Singer가 비활성화되어 있습니다. CLONE_VOICE_SOULX_SINGER_ENABLED=true로 설정하세요.", "SoulX-Singer is disabled. Set CLONE_VOICE_SOULX_SINGER_ENABLED=true.")
        elif sys.platform != "darwin":
            message = tr("현재 SoulX-Singer runtime은 Apple Silicon macOS용입니다.", "The SoulX-Singer runtime currently supports Apple Silicon macOS only.")
        elif not (self.repo_dir / "scripts/inference_mlx_bridge.py").exists():
            message = tr(
                f"SoulX-Singer runtime을 찾지 못했습니다: {self.repo_dir}. 루트에서 ./download-models.sh --soulx-singer 를 실행하세요.",
                f"SoulX-Singer runtime not found: {self.repo_dir}. Run ./download-models.sh --soulx-singer from the project root.",
            )
        elif self.settings.soulx_singer_python and not Path(self.python_executable).exists():
            message = tr(f"SoulX-Singer Python을 찾지 못했습니다: {self.settings.soulx_singer_python}.", f"SoulX-Singer Python not found: {self.settings.soulx_singer_python}.")
        elif not self.settings.soulx_singer_python and not self.local_python.exists():
            message = tr(f"SoulX-Singer 가상환경을 찾지 못했습니다: {self.local_python}.", f"SoulX-Singer virtual environment not found: {self.local_python}.")
        elif not (self.model_dir / "mlx_manifest.json").exists() or not list((self.model_dir / "svc").glob("*.safetensors")):
            message = tr(f"SoulX-Singer SVC weights를 찾지 못했습니다: {self.model_dir}.", f"SoulX-Singer SVC weights not found: {self.model_dir}.")
        elif not (self.preprocess_model_dir / "rmvpe/rmvpe.pt").exists():
            message = tr(f"SoulX-Singer RMVPE weights를 찾지 못했습니다: {self.preprocess_model_dir}.", f"SoulX-Singer RMVPE weights not found: {self.preprocess_model_dir}.")
        elif not (self.preprocess_model_dir / "mel-band-roformer-karaoke/mel_band_roformer_karaoke_becruily.ckpt").exists():
            message = tr(f"보컬 분리 weights를 찾지 못했습니다: {self.preprocess_model_dir}.", f"Vocal-separation weights not found: {self.preprocess_model_dir}.")
        elif not (self.whisper_model_dir / "model.safetensors").exists():
            message = tr(f"Whisper content encoder를 찾지 못했습니다: {self.whisper_model_dir}.", f"Whisper content encoder not found: {self.whisper_model_dir}.")
        else:
            state = "available"
            loaded = True
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.soulx_singer_enabled,
            loaded=loaded,
            model_id="mlx-community/SoulX-Singer-bf16 (SVC)",
            device=self.settings.soulx_singer_device,
            status=state,
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=message,
        )

    def preload(self) -> RuntimeModelStatus:
        status = self.status()
        if status.status != "available":
            return status
        completed = subprocess.run(
            [self.python_executable, str(self.runner_script), "--help"],
            cwd=self.runner_script.parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "SoulX-Singer dependency check failed.").strip()
            return status.model_copy(update={"loaded": False, "status": "unavailable", "message": detail[-1200:]})
        return status

    def convert_voice(self, source_audio: Path, target_voice: VoiceProfile | None, **kwargs) -> EngineOutput:
        status = self.status()
        if status.status != "available":
            raise ModelUnavailableError(status.message or tr("SoulX-Singer가 설정되지 않았습니다.", "SoulX-Singer is not set up."))
        if target_voice is None or not target_voice.audio_path:
            raise RuntimeError(tr("AI 커버에는 대상 목소리의 기준 음성이 필요합니다.", "An AI cover needs the reference audio of the target voice."))

        source_audio = source_audio.resolve()
        target_audio = Path(target_voice.audio_path).resolve()
        if not target_audio.exists():
            raise RuntimeError(f"Target voice reference file was not found: {target_audio}")

        def option(name: str, default):
            value = kwargs.get(name)
            return default if value is None else value

        conversion_mode = str(kwargs.get("conversion_mode") or "singing")
        if conversion_mode != "singing":
            raise RuntimeError(tr("SoulX-Singer는 노래 AI 커버 변환만 지원합니다.", "SoulX-Singer only supports singing AI covers."))
        steps = int(option("steps", self.settings.soulx_singer_steps))
        cfg_scale = float(option("cfg_scale", self.settings.soulx_singer_cfg_scale))
        auto_shift = bool(option("auto_shift", True))
        pitch_shift = int(option("pitch_shift", 0))
        separate_vocals = bool(option("separate_vocals", self.settings.soulx_singer_separate_vocals))
        mix_accompaniment = bool(option("mix_accompaniment", self.settings.soulx_singer_mix_accompaniment))
        seed = int(option("seed", 42))

        output_dir = self.settings.outputs_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="soulx-singer-", dir=output_dir) as temporary_dir:
            work_dir = Path(temporary_dir)
            command = [
                self.python_executable,
                str(self.runner_script),
                "--repo-dir",
                str(self.repo_dir),
                "--model-dir",
                str(self.model_dir),
                "--preprocess-model-dir",
                str(self.preprocess_model_dir),
                "--whisper-model-dir",
                str(self.whisper_model_dir),
                "--source",
                str(source_audio),
                "--target-voice",
                str(target_audio),
                "--output-dir",
                str(work_dir),
                "--device",
                self.settings.soulx_singer_device,
                "--steps",
                str(steps),
                "--cfg-scale",
                str(cfg_scale),
                "--pitch-shift",
                str(pitch_shift),
                "--seed",
                str(seed),
                "--auto-shift" if auto_shift else "--no-auto-shift",
                "--separate-vocals" if separate_vocals else "--no-separate-vocals",
                "--mix-accompaniment" if mix_accompaniment else "--no-mix-accompaniment",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.soulx_singer_timeout_seconds,
                    check=False,
                    env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"},
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    tr(f"SoulX-Singer 변환이 {self.settings.soulx_singer_timeout_seconds}초 제한을 초과했습니다.", f"SoulX-Singer conversion exceeded the {self.settings.soulx_singer_timeout_seconds}-second limit.")
                ) from exc
            if completed.returncode != 0:
                detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
                raise RuntimeError((detail or tr("SoulX-Singer 실행 중 오류가 발생했습니다.", "SoulX-Singer failed while running."))[-2000:])
            generated = work_dir / "final.wav"
            if not generated.exists():
                raise RuntimeError(tr("SoulX-Singer가 최종 WAV 파일을 만들지 못했습니다.", "SoulX-Singer did not produce the final WAV file."))
            output = output_dir / f"{uuid4().hex}.wav"
            shutil.copyfile(generated, output)
        try:
            info = sf.info(output)
            duration = float(info.frames / info.samplerate) if info.samplerate else None
        except Exception:
            duration = None
        return EngineOutput(path=output, duration_seconds=duration)


@register_adapter
class StableAudioSfxAdapter(BaseModelAdapter):
    model_id = "stable-audio-sfx"
    label = "Stable Audio 3 SFX"
    provider = "Stability AI"
    homepage = "https://github.com/Stability-AI/stable-audio-3"
    license = "Stability AI Community License (weights), MIT (code)"
    platforms = ("macOS (Apple Silicon)",)
    install_command = "./download-models.sh --sfx"
    sample_rate = STABLE_AUDIO_SAMPLE_RATE

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = StableAudioSfxEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(sound_effect_generation=True)

    @property
    def recommended_for(self) -> list[str]:
        return tr(["효과음 생성", "Apple Silicon MLX", "최대 30초 클립", "seed 기반 재현"], ["Sound-effect generation", "Apple Silicon MLX", "Clips up to 30 s", "Seed-reproducible"])

    def status(self) -> RuntimeModelStatus:
        engine_status = self.engine.status()
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.stable_audio_sfx_enabled,
            loaded=engine_status.loaded,
            model_id="stabilityai/stable-audio-3-small-sfx",
            device="mlx",
            status="available" if engine_status.available else "unavailable",
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=engine_status.message,
        )

    def preload(self) -> RuntimeModelStatus:
        return self.status()

    def generate_sound_effect(self, **kwargs) -> EngineOutput:
        path, duration = self.engine.generate(**kwargs)
        return EngineOutput(path=path, duration_seconds=duration)


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        unknown = [model_id for model_id in settings.registered_model_ids if model_id not in ADAPTER_REGISTRY]
        if unknown:
            logger.warning("Ignoring unknown CLONE_VOICE_REGISTERED_MODELS ids: %s (known: %s)", ", ".join(unknown), ", ".join(sorted(ADAPTER_REGISTRY)))
        self.adapters: dict[str, BaseModelAdapter] = {
            model_id: ADAPTER_REGISTRY[model_id](settings)
            for model_id in settings.registered_model_ids
            if model_id in ADAPTER_REGISTRY
        }

    def list(self) -> list[RuntimeModelStatus]:
        return [self._describe(adapter) for adapter in self.adapters.values()]

    def _describe(self, adapter: BaseModelAdapter) -> RuntimeModelStatus:
        return self._describe_status(adapter.status(), adapter)

    def configured_default(self, domain: ModelDomain) -> str:
        return {
            "voice": self.settings.default_tts_model,
            "cover": self.settings.default_vc_model,
            "sfx": self.settings.default_sfx_model,
            "music": self.settings.default_music_model,
        }[domain]

    def _fallback_model_id(self, purpose: str) -> str | None:
        domain = PURPOSE_DOMAIN.get(purpose, "voice")
        capability = DOMAIN_CAPABILITY[domain]
        for model_id, adapter in self.adapters.items():
            if getattr(adapter.capabilities, capability, False):
                return model_id
        return None

    def get(self, model_id: str | None, purpose: str = "tts") -> BaseModelAdapter:
        domain = PURPOSE_DOMAIN.get(purpose, "voice")
        selected = model_id or self.configured_default(domain)
        adapter = self.adapters.get(selected) if selected else None
        if adapter is None and model_id is None:
            selected = self._fallback_model_id(purpose)
            adapter = self.adapters.get(selected) if selected else None
        if adapter is None:
            raise ModelUnavailableError(f"Unknown model: {selected or purpose}")
        return adapter

    def preload(self, model_id: str) -> RuntimeModelStatus:
        adapter = self.get(model_id)
        return self._describe_status(adapter.preload(), adapter)

    @staticmethod
    def _describe_status(status: RuntimeModelStatus, adapter: BaseModelAdapter) -> RuntimeModelStatus:
        return status.model_copy(
            update={
                "domains": domains_for(status.capabilities),
                "homepage": adapter.homepage,
                "license": adapter.license,
                "platforms": list(adapter.platforms),
                "install_command": adapter.install_command,
            }
        )


def get_model_router(settings: Settings | None = None) -> ModelRouter:
    resolved_settings = settings or get_settings()
    cache_key = id(resolved_settings)
    router = _MODEL_ROUTER_CACHE.get(cache_key)
    if router is None:
        router = ModelRouter(resolved_settings)
        _MODEL_ROUTER_CACHE[cache_key] = router
    return router


_MODEL_ROUTER_CACHE: dict[int, ModelRouter] = {}
