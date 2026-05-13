from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import soundfile as sf

from app.config import Settings
from app.schemas import ModelStatus, VoiceProfile

COSYVOICE_SAMPLE_RATE = 24000


@dataclass(frozen=True)
class CosyVoiceWorkerResult:
    path: Path
    duration_seconds: float | None
    sample_rate: int | None = None


class CosyVoiceEngine:
    engine_name = "cosyvoice"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.output_dir = settings.outputs_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._load_error: str | None = None
        self._loaded = False

    @property
    def repo_dir(self) -> Path:
        return self.settings.cosyvoice_repo_dir.expanduser().resolve()

    @property
    def runner_script(self) -> Path:
        return Path(__file__).resolve().parents[2] / "scripts" / "run_cosyvoice.py"

    @property
    def python_executable(self) -> str:
        if self.settings.cosyvoice_python:
            return self.settings.cosyvoice_python
        local_python = self.repo_dir / ".venv" / "bin" / "python"
        if local_python.exists():
            return str(local_python)
        return sys.executable

    def model_dir_for_status(self) -> Path | None:
        model_dir = self.settings.cosyvoice_model_dir.strip()
        path = Path(model_dir).expanduser()
        if path.is_absolute():
            return path
        return self.repo_dir / path

    def status(self) -> ModelStatus:
        error = self._configuration_error()
        return ModelStatus(
            engine=self.engine_name,
            loaded=self._loaded,
            model_id=self.settings.cosyvoice_model_dir,
            device=self._device_label(),
            error=error or self._load_error,
        )

    def preload(self) -> ModelStatus:
        error = self._configuration_error()
        if error:
            self._load_error = error
            self._loaded = False
            raise RuntimeError(error)
        self._run_worker(check_only=True)
        self._loaded = True
        self._load_error = None
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
        denoise: bool = False,
        position_temperature: float = 0.0,
        class_temperature: float = 0.0,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
    ) -> tuple[Path, float | None]:
        del duration, num_step, guidance_scale, denoise, position_temperature, class_temperature
        del preprocess_prompt, postprocess_output, audio_chunk_duration, audio_chunk_threshold
        error = self._configuration_error()
        if error:
            self._load_error = error
            self._loaded = False
            raise RuntimeError(error)

        prompt_wav = None
        prompt_text = None
        if voice is not None and voice.audio_path:
            prompt_wav = str(Path(voice.audio_path).expanduser().resolve())
            prompt_text = voice.transcript or None
        elif self.settings.cosyvoice_prompt_wav:
            prompt_wav = str(Path(self.settings.cosyvoice_prompt_wav).expanduser().resolve())
            prompt_text = self.settings.cosyvoice_prompt_text or None

        result = self._run_worker(
            text=" ".join(text.split()),
            prompt_wav=prompt_wav,
            prompt_text=prompt_text,
            prefer_voice_clone=voice is not None and bool(voice.audio_path),
            instruct=instruct,
            language=language,
            speed=speed,
            check_only=False,
        )
        self._loaded = True
        self._load_error = None
        return result.path, result.duration_seconds

    def _configuration_error(self) -> str | None:
        if not self.settings.cosyvoice_enabled:
            return "CosyVoice is disabled by CLONE_VOICE_COSYVOICE_ENABLED=false."
        if not self.runner_script.exists():
            return f"CosyVoice runner was not found: {self.runner_script}."
        if not (self.repo_dir / "cosyvoice" / "cli" / "cosyvoice.py").exists():
            return (
                f"CosyVoice repo was not found at {self.repo_dir}. "
                "Clone https://github.com/FunAudioLLM/CosyVoice there or set CLONE_VOICE_COSYVOICE_REPO_DIR."
            )
        python = Path(self.python_executable)
        if self.settings.cosyvoice_python and not python.exists():
            return f"CosyVoice Python executable was not found: {python}."
        model_path = self.model_dir_for_status()
        if model_path and not model_path.exists() and not self.settings.cosyvoice_allow_model_download:
            return (
                f"CosyVoice model was not found at {model_path}. "
                "Download a pretrained model into that path or set CLONE_VOICE_COSYVOICE_ALLOW_MODEL_DOWNLOAD=true."
            )
        if self.settings.cosyvoice_prompt_wav and not Path(self.settings.cosyvoice_prompt_wav).expanduser().exists():
            return f"CosyVoice default prompt wav was not found: {self.settings.cosyvoice_prompt_wav}."
        return None

    def _run_worker(
        self,
        *,
        text: str | None = None,
        prompt_wav: str | None = None,
        prompt_text: str | None = None,
        prefer_voice_clone: bool = False,
        instruct: str | None = None,
        language: str | None = None,
        speed: float = 1.0,
        check_only: bool = False,
    ) -> CosyVoiceWorkerResult:
        work_dir = (self.output_dir / f"{uuid4().hex}-cosyvoice").resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        output_path = (self.output_dir / f"{uuid4().hex}.wav").resolve()
        input_json = work_dir / "request.json"
        result_json = work_dir / "result.json"
        payload = {
            "repo_dir": str(self.repo_dir),
            "model_dir": self.settings.cosyvoice_model_dir,
            "allow_model_download": self.settings.cosyvoice_allow_model_download,
            "output_path": str(output_path),
            "result_json": str(result_json),
            "text": text or "모델 로딩 확인입니다.",
            "prompt_wav": prompt_wav,
            "prompt_text": prompt_text,
            "prefer_voice_clone": prefer_voice_clone,
            "default_spk_id": self.settings.cosyvoice_default_spk_id,
            "instruct": instruct,
            "language": language,
            "speed": speed,
            "text_frontend": self.settings.cosyvoice_text_frontend,
            "fp16": self.settings.cosyvoice_fp16,
            "check_only": check_only,
        }
        input_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            completed = subprocess.run(
                [self.python_executable, str(self.runner_script), str(input_json)],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=self.settings.cosyvoice_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"CosyVoice generation timed out after {self.settings.cosyvoice_timeout_seconds}s.") from exc
        if completed.returncode != 0:
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            raise RuntimeError((detail or "CosyVoice worker exited with an error.")[-1600:])
        if not result_json.exists():
            detail = "\n".join(part for part in (completed.stderr, completed.stdout) if part).strip()
            raise RuntimeError(("CosyVoice worker did not write a result file. " + detail)[-1600:])
        result = json.loads(result_json.read_text(encoding="utf-8"))
        if result.get("ok") is not True:
            raise RuntimeError(str(result.get("error") or "CosyVoice worker failed."))
        if check_only:
            return CosyVoiceWorkerResult(path=output_path, duration_seconds=None, sample_rate=result.get("sample_rate"))
        result_path = Path(result["path"]).resolve()
        if not result_path.exists():
            raise RuntimeError(f"CosyVoice worker reported a missing output file: {result_path}")
        duration = result.get("duration_seconds")
        if duration is None:
            try:
                info = sf.info(result_path)
                duration = float(info.frames / info.samplerate) if info.samplerate else None
            except Exception:
                duration = None
        return CosyVoiceWorkerResult(path=result_path, duration_seconds=duration, sample_rate=result.get("sample_rate"))

    def _device_label(self) -> str:
        if self.settings.cosyvoice_device != "auto":
            return self.settings.cosyvoice_device
        if self.settings.cosyvoice_python:
            return "auto"
        try:
            import torch
        except Exception:
            return "auto"
        if torch.cuda.is_available():
            return "cuda:0"
        return "cpu"
