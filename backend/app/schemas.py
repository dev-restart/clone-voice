from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class VoiceProfile(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    transcript: str | None = None
    audio_path: str
    audio_url: str
    source_audio_path: str | None = None
    source_audio_url: str | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    kind: Literal["custom", "preset"] = "custom"
    description: str | None = None
    language: str | None = None
    avatar: str | None = None
    is_default: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VoiceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    transcript: str | None = None
    trim_start: float | None = Field(default=None, ge=0)
    trim_end: float | None = Field(default=None, gt=0)


class GenerateRequest(BaseModel):
    text: str
    progress_id: str | None = None
    model_id: str | None = None
    voice_id: str | None = None
    instruct: str | None = None
    style_prompt: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    duration: float | None = Field(default=None, ge=1.0, le=300.0)
    num_step: int = Field(default=32, ge=4, le=64)
    guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    denoise: bool = True
    position_temperature: float = Field(default=0.0, ge=0.0, le=20.0)
    class_temperature: float = Field(default=0.0, ge=0.0, le=5.0)
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    audio_chunk_duration: float = Field(default=15.0, ge=5.0, le=120.0)
    audio_chunk_threshold: float = Field(default=30.0, ge=5.0, le=600.0)
    quality: Literal["fast", "balanced", "high"] = "balanced"
    pitch_shift: float = Field(default=0.0, ge=-6.0, le=6.0)
    volume_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0)
    normalize_output: bool = True
    tone_prompt: str | None = None
    language: str | None = None
    accent: str | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Text is required")
        return cleaned


class GenerateResponse(BaseModel):
    text: str
    voice_id: str | None
    audio_url: str
    duration_seconds: float | None = None
    model_id: str | None = None


class SpeechToSpeechResponse(GenerateResponse):
    transcript: str


class ModelCapabilities(BaseModel):
    tts: bool = False
    voice_clone_tts: bool = False
    voice_design: bool = False
    stt: bool = False
    voice_conversion: bool = False
    singing_voice_conversion: bool = False
    realtime_voice_conversion: bool = False


class RuntimeModelStatus(BaseModel):
    id: str
    label: str
    provider: str
    status: Literal["available", "unavailable"]
    enabled: bool
    loaded: bool = False
    model_id: str | None = None
    device: str | None = None
    sample_rate: int = 24000
    capabilities: ModelCapabilities
    recommended_for: list[str] = Field(default_factory=list)
    message: str | None = None


class ModelPreference(BaseModel):
    id: str
    enabled: bool = True
    order: int = 0


class ModelPreferencesUpdateRequest(BaseModel):
    model_preferences: dict[str, ModelPreference] = Field(default_factory=dict)
    default_tts_model: str | None = None
    default_vc_model: str | None = None


class ModelPreferencesResponse(BaseModel):
    model_preferences: dict[str, ModelPreference] = Field(default_factory=dict)
    default_tts_model: str
    default_vc_model: str


class ModelListResponse(BaseModel):
    models: list[RuntimeModelStatus]
    default_tts_model: str
    default_vc_model: str
    model_preferences: dict[str, ModelPreference] = Field(default_factory=dict)


class TTSRequest(GenerateRequest):
    tone_prompt: str | None = None
    language: str | None = None
    accent: str | None = None


class StorySegmentRequest(BaseModel):
    id: str | None = None
    text: str
    language: str = "ko"
    voice_id: str | None = None
    model_id: str | None = None
    tone_prompt: str | None = None
    accent: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pause_after_ms: int = Field(default=450, ge=0, le=5000)

    @field_validator("text")
    @classmethod
    def segment_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Segment text is required")
        return cleaned


class StoryStudioGenerateRequest(BaseModel):
    title: str = "새 스토리북"
    progress_id: str | None = None
    default_model_id: str | None = None
    num_step: int = Field(default=32, ge=4, le=64)
    guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    denoise: bool = True
    normalize_output: bool = True
    segments: list[StorySegmentRequest]

    @field_validator("segments")
    @classmethod
    def segments_must_not_be_empty(cls, value: list[StorySegmentRequest]) -> list[StorySegmentRequest]:
        if not value:
            raise ValueError("At least one story segment is required")
        return value[:80]


class StorySegmentResult(BaseModel):
    id: str
    index: int
    text: str
    language: str
    voice_id: str | None = None
    voice_name: str | None = None
    model_id: str | None = None
    audio_url: str
    duration_seconds: float | None = None
    pause_after_ms: int = 0
    tone_prompt: str | None = None
    effective_instruct: str | None = None


class StoryStudioGenerateResponse(BaseModel):
    title: str
    audio_url: str
    duration_seconds: float
    segments: list[StorySegmentResult]


class STTResponse(BaseModel):
    id: str
    text: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str | None = None
    audio_url: str | None = None
    provider: str = "whisper"
    model: str


class VoiceConversionResponse(GenerateResponse):
    transcript: str | None = None
    conversion_mode: str | None = None
    seed_vc_options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class UploadedAudioResponse(BaseModel):
    audio_url: str
    audio_path: str
    filename: str


class YouTubeImportRequest(BaseModel):
    url: str
    isolate_voice: bool = False

    @field_validator("url")
    @classmethod
    def url_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("YouTube URL is required")
        return cleaned


class YouTubeImportResponse(BaseModel):
    title: str
    webpage_url: str
    duration_seconds: float | None = None
    audio_url: str
    audio_path: str
    filename: str
    voice_isolated: bool = False


class VoiceConversionJobItem(BaseModel):
    id: str
    model_id: str
    source_audio_path: str
    target_voice_id: str | None = None
    output_audio_url: str
    transcript: str | None = None
    created_at: datetime


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSegmentsResponse(BaseModel):
    segments: list[TranscriptSegment]
    text: str


class TranslateRequest(BaseModel):
    text: str
    languages: list[str] = Field(default_factory=lambda: ["en", "ja"])

    @field_validator("text")
    @classmethod
    def translation_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Text is required")
        return cleaned

    @field_validator("languages")
    @classmethod
    def languages_must_not_be_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("At least one target language is required")
        return cleaned[:8]


class TranslateResponse(BaseModel):
    source_text: str
    translations: dict[str, str]
    provider: str
    model: str


class SmokeTestRequest(BaseModel):
    text: str = "안녕하세요. 테스트 음성입니다."
    languages: list[str] = Field(default_factory=lambda: ["en"])


class SmokeTestResponse(BaseModel):
    ok: bool
    detail: str
    audio_url: str | None = None
    translations: dict[str, str] | None = None


class ContentResult(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    language: str
    text: str
    voice_id: str | None = None
    voice_name: str | None = None
    model_id: str | None = None
    audio_url: str
    duration_seconds: float | None = None
    tone_prompt: str | None = None
    style_prompt: str | None = None
    effective_instruct: str | None = None
    language_hint: str | None = None
    accent_hint: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    source_text: str
    translations: dict[str, str] = Field(default_factory=dict)
    results: list[ContentResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentCreateRequest(BaseModel):
    title: str
    source_text: str
    translations: dict[str, str] = Field(default_factory=dict)


class ContentUpdateRequest(BaseModel):
    title: str | None = None
    source_text: str | None = None
    translations: dict[str, str] | None = None


class ContentGenerateRequest(BaseModel):
    model_id: str | None = None
    voice_id: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["ko"])
    tone_prompt: str | None = None
    style_prompt: str | None = None
    accent: str | None = None
    progress_id: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    duration: float | None = Field(default=None, ge=1.0, le=300.0)
    num_step: int = Field(default=32, ge=4, le=64)
    guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    denoise: bool = True
    position_temperature: float = Field(default=0.0, ge=0.0, le=20.0)
    class_temperature: float = Field(default=0.0, ge=0.0, le=5.0)
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    audio_chunk_duration: float = Field(default=15.0, ge=5.0, le=120.0)
    audio_chunk_threshold: float = Field(default=30.0, ge=5.0, le=600.0)
    pitch_shift: float = Field(default=0.0, ge=-6.0, le=6.0)
    volume_gain_db: float = Field(default=0.0, ge=-12.0, le=12.0)
    normalize_output: bool = True


class GenerationPreviewRequest(BaseModel):
    voice_id: str | None = None
    language: str = "ko"
    tone_prompt: str | None = None
    accent: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    duration: float | None = Field(default=None, ge=1.0, le=300.0)


class GenerationPreviewResponse(BaseModel):
    mode: Literal["clone", "design", "auto"]
    voice_id: str | None = None
    voice_name: str | None = None
    language: str
    language_hint: str | None = None
    accent_hint: str | None = None
    tone_prompt: str | None = None
    effective_instruct: str | None = None
    speed: float
    duration: float | None = None
    notes: list[str] = Field(default_factory=list)


class ResultSaveVoiceRequest(BaseModel):
    name: str | None = None
    transcript: str | None = None
    trim_start: float | None = Field(default=None, ge=0)
    trim_end: float | None = Field(default=None, gt=0)


class ModelStatus(BaseModel):
    engine: str
    loaded: bool
    model_id: str | None = None
    device: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    ok: bool
    model: ModelStatus


def public_file_url(path: Path, bucket: str) -> str:
    return f"/api/files/{bucket}/{path.name}"
