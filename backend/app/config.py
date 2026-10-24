from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


DEFAULT_REGISTERED_MODELS = ("voxcpm", "soulx-singer", "stable-audio-sfx")


class Settings(BaseSettings):
    app_name: str = "Clone Voice Studio"
    storage_dir: Path = Field(default=Path("storage"))
    # Downloaded model weights (Hugging Face cache, Whisper). Ignored by Git.
    models_dir: Path = Field(default=Path("models"))
    voice_dir: Path | None = None
    upload_dir: Path | None = None
    output_dir: Path | None = None
    content_dir: Path | None = None
    media_import_cookie_file: Path | None = None
    media_import_max_duration_seconds: int = Field(default=3600, ge=60, le=86400)
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
    # Experimental second TTS engine. Off by default and not in DEFAULT_REGISTERED_MODELS; it needs its
    # own venv (qwen-tts pins transformers==4.57.3).
    qwen3_tts_enabled: bool = False
    qwen3_tts_python: str | None = None
    qwen3_tts_model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    qwen3_tts_device: str = "auto"
    qwen3_tts_dtype: str = "float32"
    qwen3_tts_cache_dir: Path | None = None  # falls back to voxcpm_cache_dir
    qwen3_tts_local_files_only: bool = False
    qwen3_tts_timeout_seconds: int = 900
    soulx_singer_enabled: bool = False
    soulx_singer_repo_dir: Path = Field(default=Path("vendor/SoulX-Singer-MLX"))
    soulx_singer_python: str | None = None
    soulx_singer_model_dir: Path = Field(default=Path("models/SoulX-Singer-bf16"))
    soulx_singer_preprocess_model_dir: Path = Field(default=Path("pretrained_models/SoulX-Singer-Preprocess"))
    soulx_singer_whisper_model_dir: Path = Field(default=Path("pretrained_models/openai__whisper-base"))
    soulx_singer_device: str = "mps"
    soulx_singer_steps: int = 4
    soulx_singer_cfg_scale: float = 2.0
    soulx_singer_separate_vocals: bool = True
    soulx_singer_mix_accompaniment: bool = True
    soulx_singer_timeout_seconds: int = 3600
    stable_audio_sfx_enabled: bool = False
    stable_audio_repo_dir: Path = Field(default=Path("vendor/stable-audio-3"))
    stable_audio_python: str | None = None
    stable_audio_timeout_seconds: int = 300
    registered_models: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(DEFAULT_REGISTERED_MODELS))
    default_tts_model: str = "voxcpm"
    default_vc_model: str = "soulx-singer"
    default_sfx_model: str = "stable-audio-sfx"
    default_music_model: str = ""
    whisper_model: str = "base"
    apple_speech_require_on_device: bool = True
    apple_speech_timeout_seconds: int = 180
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen3:4b"
    llm_api_key: str = "ollama"
    llm_timeout_seconds: int = 120
    apple_intelligence_timeout_seconds: int = Field(default=120, ge=5, le=600)
    ai_text_settings_path: Path | None = None
    codex_cli_bin: str = "codex"
    kimi_cli_bin: str = "kimi"
    ai_cli_timeout_seconds: int = 120

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
        "media_import_cookie_file",
        "cosyvoice_python",
        "cosyvoice_default_spk_id",
        "cosyvoice_prompt_wav",
        "cosyvoice_prompt_text",
        "soulx_singer_python",
        "stable_audio_python",
        "ai_text_settings_path",
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

        # Ids are checked against the adapter registry in ModelRouter, where plugins have already registered.
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

    @property
    def resolved_ai_text_settings_path(self) -> Path:
        return self.ai_text_settings_path or (self.storage_dir / "ai_text_settings.json")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.voices_dir, settings.outputs_dir, settings.uploads_dir, settings.contents_dir):
        directory.mkdir(parents=True, exist_ok=True)
    from app.model_cache import resolve_voxcpm_cache_dir

    settings.voxcpm_cache_dir = resolve_voxcpm_cache_dir(settings)
    return settings
