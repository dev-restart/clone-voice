from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from app.config import Settings, get_settings
from app.schemas import ModelCapabilities, RuntimeModelStatus, VoiceProfile
from app.services.audio_utils import REFERENCE_SAMPLE_RATE
from app.services.cosyvoice_service import COSYVOICE_SAMPLE_RATE, CosyVoiceEngine
from app.services.omnivoice_service import OmniVoiceEngine
from app.services.voxcpm_service import VOXCPM_SAMPLE_RATE, VoxCPMEngine


class ModelUnavailableError(RuntimeError):
    pass


class CapabilityUnsupportedError(RuntimeError):
    pass


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

    def realtime_status(self) -> dict:
        raise CapabilityUnsupportedError(f"{self.label} does not support real-time voice conversion.")

    def launch_realtime(self, **kwargs) -> dict:
        raise CapabilityUnsupportedError(f"{self.label} does not support real-time voice conversion.")


class OmniVoiceAdapter(BaseModelAdapter):
    model_id = "omnivoice"
    label = "OmniVoice"
    provider = "k2-fsa"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = OmniVoiceEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True, voice_clone_tts=True, voice_design=True, stt=True)

    @property
    def recommended_for(self) -> list[str]:
        return ["초고속 추론", "다국어 TTS", "등록 목소리 복제"]

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


class VoxCPMAdapter(BaseModelAdapter):
    model_id = "voxcpm"
    label = "VoxCPM2"
    provider = "OpenBMB"
    sample_rate = VOXCPM_SAMPLE_RATE

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.engine = VoxCPMEngine(settings)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tts=True, voice_clone_tts=True, voice_design=True)

    @property
    def recommended_for(self) -> list[str]:
        return ["48kHz 고품질 TTS", "한국어 포함 30개 언어", "스타일 제어 음성 복제"]

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
        return ["다국어 zero-shot TTS", "등록 목소리 복제", "CosyVoice2/3 교체 가능", "별도 Python 3.10 런타임"]

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


class SeedVCAdapter(BaseModelAdapter):
    model_id = "seed-vc"
    label = "Seed-VC"
    provider = "Plachtaa/seed-vc"

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(voice_conversion=True, singing_voice_conversion=True, realtime_voice_conversion=True)

    @property
    def recommended_for(self) -> list[str]:
        return ["원본 음성 직접 변환", "보컬/SVC 변환", "F0/피치 제어", "zero-shot voice conversion", "Mac M Series 로컬 실행"]

    @property
    def repo_dir(self) -> Path:
        return self.settings.seed_vc_repo_dir.resolve()

    @property
    def inference_script(self) -> Path:
        return self.repo_dir / "inference.py"

    @property
    def inference_v2_script(self) -> Path:
        return self.repo_dir / "inference_v2.py"

    @property
    def realtime_script(self) -> Path:
        return self.repo_dir / "real-time-gui.py"

    @property
    def python_executable(self) -> str:
        if self.settings.seed_vc_python:
            return self.settings.seed_vc_python
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
        if not self.settings.seed_vc_enabled:
            message = "Seed-VC is disabled by CLONE_VOICE_SEED_VC_ENABLED=false."
        elif not self.inference_script.exists():
            message = (
                f"Seed-VC repo was not found at {self.repo_dir}. "
                "Clone https://github.com/Plachtaa/seed-vc there or set CLONE_VOICE_SEED_VC_REPO_DIR."
            )
        elif self.settings.seed_vc_python and not Path(self.settings.seed_vc_python).exists():
            message = f"Seed-VC Python executable was not found: {self.settings.seed_vc_python}."
        elif not self.settings.seed_vc_python and not self.local_python.exists():
            message = (
                f"Seed-VC Python environment was not found at {self.local_python}. "
                "Run `uv run python scripts/setup_seed_vc.py` from the backend directory."
            )
        else:
            state = "available"
            loaded = True
        return RuntimeModelStatus(
            id=self.model_id,
            label=self.label,
            provider=self.provider,
            enabled=self.settings.seed_vc_enabled,
            loaded=loaded,
            model_id="seed-vc",
            device=self.settings.seed_vc_device,
            status=state,
            sample_rate=self.sample_rate,
            capabilities=self.capabilities,
            recommended_for=self.recommended_for,
            message=message,
        )

    def realtime_status(self) -> dict:
        status = self.status()
        if status.status != "available":
            return {"available": False, "running": False, "message": status.message}
        if not self.realtime_script.exists():
            return {"available": False, "running": False, "message": f"Seed-VC real-time GUI was not found: {self.realtime_script}"}
        return {"available": True, "running": False, "message": "Seed-VC real-time GUI can be launched on this machine."}

    def launch_realtime(self, **kwargs) -> dict:
        status = self.realtime_status()
        if not status["available"]:
            raise ModelUnavailableError(status["message"])
        command = [self.python_executable, str(self.realtime_script)]
        checkpoint = kwargs.get("checkpoint_path") or self.settings.seed_vc_checkpoint
        config = kwargs.get("config_path") or self.settings.seed_vc_config
        fp16 = kwargs.get("fp16", self.settings.seed_vc_fp16)
        gpu = kwargs.get("gpu", 0)
        if bool(checkpoint) != bool(config):
            raise RuntimeError("Seed-VC real-time custom checkpoint and config must be provided together.")
        if checkpoint and config:
            checkpoint_path = Path(str(checkpoint)).expanduser()
            config_path = Path(str(config)).expanduser()
            if not checkpoint_path.exists():
                raise RuntimeError(f"Seed-VC real-time checkpoint was not found: {checkpoint_path}")
            if not config_path.exists():
                raise RuntimeError(f"Seed-VC real-time config was not found: {config_path}")
            command.extend(["--checkpoint-path", str(checkpoint_path), "--config-path", str(config_path)])
        command.extend(["--fp16", str(bool(fp16)), "--gpu", str(int(gpu))])
        process = subprocess.Popen(command, cwd=self.repo_dir)
        return {
            "available": True,
            "running": True,
            "pid": process.pid,
            "message": "Seed-VC real-time GUI launched. Select input/output devices in the launched window.",
        }

    def preload(self) -> RuntimeModelStatus:
        status = self.status()
        if status.status != "available":
            return status
        completed = subprocess.run(
            [self.python_executable, str(self.inference_script), "--help"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Seed-VC dependency check failed.").strip()
            return status.model_copy(update={"loaded": False, "status": "unavailable", "message": detail[-1200:]})
        return status

    def convert_voice(self, source_audio: Path, target_voice: VoiceProfile | None, **kwargs) -> EngineOutput:
        status = self.status()
        if status.status != "available":
            raise ModelUnavailableError(status.message or "Seed-VC is not configured.")
        if target_voice is None or not target_voice.audio_path:
            raise RuntimeError("Seed-VC voice conversion requires a target voice reference.")

        source_audio = source_audio.resolve()
        target_audio = Path(target_voice.audio_path).resolve()
        if not target_audio.exists():
            raise RuntimeError(f"Target voice reference file was not found: {target_audio}")

        work_dir = (self.settings.outputs_dir / f"{uuid4().hex}-seed-vc").resolve()
        work_dir.mkdir(parents=True, exist_ok=True)

        def option(name: str, default):
            value = kwargs.get(name)
            return default if value is None else value

        conversion_mode = str(kwargs.get("conversion_mode") or "voice")
        if conversion_mode not in {"voice", "singing", "v2"}:
            raise RuntimeError(f"Unsupported Seed-VC conversion mode: {conversion_mode}")
        diffusion_steps = int(option("diffusion_steps", self.settings.seed_vc_diffusion_steps))
        length_adjust = float(option("length_adjust", self.settings.seed_vc_length_adjust))
        inference_cfg_rate = float(option("inference_cfg_rate", self.settings.seed_vc_inference_cfg_rate))
        f0_condition = bool(option("f0_condition", self.settings.seed_vc_f0_condition))
        auto_f0_adjust = bool(option("auto_f0_adjust", self.settings.seed_vc_auto_f0_adjust))
        semi_tone_shift = int(option("semi_tone_shift", self.settings.seed_vc_semi_tone_shift))
        fp16 = bool(option("fp16", self.settings.seed_vc_fp16))
        checkpoint = kwargs.get("checkpoint") or self.settings.seed_vc_checkpoint
        config = kwargs.get("config") or self.settings.seed_vc_config

        if conversion_mode == "singing":
            f0_condition = True
            auto_f0_adjust = bool(option("auto_f0_adjust", True))
            diffusion_steps = int(option("diffusion_steps", max(40, self.settings.seed_vc_diffusion_steps)))

        if conversion_mode == "v2":
            command = [
                self.python_executable,
                str(self.inference_v2_script),
                "--source",
                str(source_audio),
                "--target",
                str(target_audio),
                "--output",
                str(work_dir),
                "--diffusion-steps",
                str(diffusion_steps),
                "--length-adjust",
                str(length_adjust),
                "--intelligibility-cfg-rate",
                str(float(option("intelligibility_cfg_rate", 0.7))),
                "--similarity-cfg-rate",
                str(float(option("similarity_cfg_rate", 0.7))),
                "--top-p",
                str(float(option("top_p", 0.9))),
                "--temperature",
                str(float(option("temperature", 1.0))),
                "--repetition-penalty",
                str(float(option("repetition_penalty", 1.0))),
                "--convert-style",
                str(bool(option("convert_style", False))),
                "--anonymization-only",
                str(bool(option("anonymization_only", False))),
            ]
            ar_checkpoint = kwargs.get("ar_checkpoint_path") or self.settings.seed_vc_v2_ar_checkpoint
            cfm_checkpoint = kwargs.get("cfm_checkpoint_path") or self.settings.seed_vc_v2_cfm_checkpoint
            if ar_checkpoint:
                command.extend(["--ar-checkpoint-path", str(ar_checkpoint)])
            if cfm_checkpoint:
                command.extend(["--cfm-checkpoint-path", str(cfm_checkpoint)])
        else:
            if bool(checkpoint) != bool(config):
                raise RuntimeError("Seed-VC custom checkpoint and config must be provided together.")
            command = [
                self.python_executable,
                str(self.inference_script),
                "--source",
                str(source_audio),
                "--target",
                str(target_audio),
                "--output",
                str(work_dir),
                "--diffusion-steps",
                str(diffusion_steps),
                "--length-adjust",
                str(length_adjust),
                "--inference-cfg-rate",
                str(inference_cfg_rate),
                "--f0-condition",
                str(f0_condition),
                "--auto-f0-adjust",
                str(auto_f0_adjust),
                "--semi-tone-shift",
                str(semi_tone_shift),
                "--fp16",
                str(fp16),
            ]
            if checkpoint and config:
                checkpoint_path = Path(str(checkpoint)).expanduser()
                config_path = Path(str(config)).expanduser()
                if not checkpoint_path.exists():
                    raise RuntimeError(f"Seed-VC checkpoint was not found: {checkpoint_path}")
                if not config_path.exists():
                    raise RuntimeError(f"Seed-VC config was not found: {config_path}")
                command.extend(["--checkpoint", str(checkpoint_path), "--config", str(config_path)])
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=self.settings.seed_vc_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Seed-VC conversion timed out after {self.settings.seed_vc_timeout_seconds}s.") from exc

        if completed.returncode != 0:
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            if not detail:
                detail = "Seed-VC exited with an error."
            raise RuntimeError(detail[-1200:])

        candidates = sorted(work_dir.rglob("*.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            message = "Seed-VC did not produce a WAV output file."
            if detail:
                message = f"{message} {detail[-1200:]}"
            raise RuntimeError(message)

        output_dir = self.settings.outputs_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{uuid4().hex}.wav"
        shutil.copyfile(candidates[0], output)
        try:
            info = sf.info(output)
            duration = float(info.frames / info.samplerate) if info.samplerate else None
        except Exception:
            duration = None
        return EngineOutput(path=output, duration_seconds=duration)


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        adapter_factories: dict[str, type[BaseModelAdapter]] = {
            "omnivoice": OmniVoiceAdapter,
            "voxcpm": VoxCPMAdapter,
            "cosyvoice": CosyVoiceAdapter,
            "seed-vc": SeedVCAdapter,
        }
        self.adapters: dict[str, BaseModelAdapter] = {
            model_id: adapter_factories[model_id](settings)
            for model_id in settings.registered_model_ids
            if model_id in adapter_factories
        }

    def list(self) -> list[RuntimeModelStatus]:
        return [adapter.status() for adapter in self.adapters.values()]

    def _fallback_model_id(self, purpose: str) -> str | None:
        for model_id, adapter in self.adapters.items():
            capabilities = adapter.capabilities
            if purpose == "voice_conversion" and capabilities.voice_conversion:
                return model_id
            if purpose != "voice_conversion" and capabilities.tts:
                return model_id
        return next(iter(self.adapters), None)

    def get(self, model_id: str | None, purpose: str = "tts") -> BaseModelAdapter:
        selected = model_id or (self.settings.default_vc_model if purpose == "voice_conversion" else self.settings.default_tts_model)
        adapter = self.adapters.get(selected)
        if adapter is None and model_id is None:
            selected = self._fallback_model_id(purpose)
            adapter = self.adapters.get(selected) if selected else None
        if adapter is None:
            raise ModelUnavailableError(f"Unknown model: {selected}")
        return adapter

    def preload(self, model_id: str) -> RuntimeModelStatus:
        return self.get(model_id).preload()


def get_model_router(settings: Settings | None = None) -> ModelRouter:
    resolved_settings = settings or get_settings()
    cache_key = id(resolved_settings)
    router = _MODEL_ROUTER_CACHE.get(cache_key)
    if router is None:
        router = ModelRouter(resolved_settings)
        _MODEL_ROUTER_CACHE[cache_key] = router
    return router


_MODEL_ROUTER_CACHE: dict[int, ModelRouter] = {}
