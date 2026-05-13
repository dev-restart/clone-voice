from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_REGISTERED_MODELS = ("omnivoice", "voxcpm", "cosyvoice", "seed-vc")


class Settings(BaseSettings):
    app_name: str = "Clone Voice Studio"
    storage_dir: Path = Field(default=Path("storage"))
    voice_dir: Path | None = None
    upload_dir: Path | None = None
    output_dir: Path | None = None
    content_dir: Path | None = None
    database_url: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]
    )
    cors_origin_regex: str | None = r"https?://(localhost|127\.0\.0\.1):\d+"
    omnivoice_enabled: bool = False
    omnivoice_model_id: str = "k2-fsa/OmniVoice"
    omnivoice_device: str = "auto"
    omnivoice_dtype: str = "auto"
    voxcpm_enabled: bool = False
    voxcpm_model_id: str = "openbmb/VoxCPM2"
    voxcpm_device: str = "auto"
    voxcpm_load_denoiser: bool = False
    voxcpm_optimize: bool = False
    voxcpm_cache_dir: Path | None = None
    voxcpm_local_files_only: bool = False
    voxcpm_inference_timesteps: int = 10
    voxcpm_max_len: int = 4096
    cosyvoice_enabled: bool = False
    cosyvoice_repo_dir: Path = Field(default=Path("vendor/CosyVoice"))
    cosyvoice_python: str | None = None
    cosyvoice_model_dir: str = "pretrained_models/CosyVoice2-0.5B"
    cosyvoice_allow_model_download: bool = False
    cosyvoice_default_spk_id: str | None = None
    cosyvoice_prompt_wav: str | None = None
    cosyvoice_prompt_text: str | None = None
    cosyvoice_text_frontend: bool = True
    cosyvoice_fp16: bool = False
    cosyvoice_device: str = "auto"
    cosyvoice_sample_rate: int = 24000
    cosyvoice_timeout_seconds: int = 1800
    seed_vc_enabled: bool = False
    seed_vc_repo_dir: Path = Field(default=Path("vendor/seed-vc"))
    seed_vc_python: str | None = None
    seed_vc_device: str = "mps"
    seed_vc_diffusion_steps: int = 25
    seed_vc_length_adjust: float = 1.0
    seed_vc_inference_cfg_rate: float = 0.7
    seed_vc_f0_condition: bool = False
    seed_vc_auto_f0_adjust: bool = False
    seed_vc_semi_tone_shift: int = 0
    seed_vc_fp16: bool = True
    seed_vc_checkpoint: str | None = None
    seed_vc_config: str | None = None
    seed_vc_v2_ar_checkpoint: str | None = None
    seed_vc_v2_cfm_checkpoint: str | None = None
    seed_vc_timeout_seconds: int = 1800
    registered_models: list[str] = Field(default_factory=lambda: list(DEFAULT_REGISTERED_MODELS))
    default_tts_model: str = "omnivoice"
    default_vc_model: str = "seed-vc"
    whisper_model: str = "base"
    apple_speech_require_on_device: bool = True
    apple_speech_timeout_seconds: int = 180
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "translategemma:12b"
    llm_api_key: str = "ollama"
    llm_timeout_seconds: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLONE_VOICE_")

    @field_validator("voxcpm_cache_dir", mode="before")
    @classmethod
    def empty_voxcpm_cache_dir_is_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator(
        "voice_dir",
        "upload_dir",
        "output_dir",
        "content_dir",
        "cosyvoice_python",
        "cosyvoice_default_spk_id",
        "cosyvoice_prompt_wav",
        "cosyvoice_prompt_text",
        mode="before",
    )
    @classmethod
    def empty_optional_values_are_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("registered_models", mode="before")
    @classmethod
    def parse_registered_models(cls, value: Any) -> Any:
        if value in (None, ""):
            return list(DEFAULT_REGISTERED_MODELS)
        if isinstance(value, str):
            if value.strip().lower() in {"*", "all"}:
                return list(DEFAULT_REGISTERED_MODELS)
            values = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            values = [str(item).strip() for item in value if str(item).strip()]
        else:
            raise ValueError("registered_models must be a comma-separated string or list")

        unknown = sorted(set(values) - set(DEFAULT_REGISTERED_MODELS))
        if unknown:
            raise ValueError(f"Unknown registered model id: {', '.join(unknown)}")
        return values or list(DEFAULT_REGISTERED_MODELS)

    @property
    def registered_model_ids(self) -> list[str]:
        seen: set[str] = set()
        ids: list[str] = []
        for model_id in self.registered_models:
            if model_id in seen:
                continue
            seen.add(model_id)
            ids.append(model_id)
        return ids

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.storage_dir / 'clone_voice.db'}"

    @property
    def voices_dir(self) -> Path:
        return self.voice_dir or (self.storage_dir / "voices")

    @property
    def outputs_dir(self) -> Path:
        return self.output_dir or (self.storage_dir / "outputs")

    @property
    def uploads_dir(self) -> Path:
        return self.upload_dir or (self.storage_dir / "uploads")

    @property
    def contents_dir(self) -> Path:
        return self.content_dir or (self.storage_dir / "contents")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.voices_dir, settings.outputs_dir, settings.uploads_dir, settings.contents_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
