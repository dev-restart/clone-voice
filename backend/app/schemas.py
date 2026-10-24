from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class VoiceProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    transcript: str | None = None
    audio_url: str
    source_audio_url: str | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    kind: Literal["custom", "preset"] = "custom"
    description: str | None = None
    language: str | None = None
    avatar: str | None = None
    is_default: bool = False
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class VoiceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    avatar: str | None = None
    transcript: str | None = None
    trim_start: float | None = Field(default=None, ge=0)
    trim_end: float | None = Field(default=None, gt=0)


class PronunciationRule(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    replacement: str = Field(min_length=1, max_length=200)
    language: Literal["all", "ko", "en", "ja", "zh", "es", "fr", "de"] = "ko"

    @field_validator("source", "replacement")
    @classmethod
    def clean_pronunciation_text(cls, value: str) -> str:
        import unicodedata

        cleaned = unicodedata.normalize("NFC", value.strip())
        if not cleaned or any(character in cleaned for character in "\n\r\t[]"):
            raise ValueError("발음 항목은 태그나 줄바꿈 없이 입력하세요.")
        return cleaned


class ContentProductionSettings(BaseModel):
    model_id: str | None = None
    voice_id: str | None = None
    language: str = Field(default="ko", min_length=1, max_length=32)
    accent: str = ""
    tone_prompt: str = ""
    style_prompt: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    normalize_output: bool = True
    quality: Literal["fast", "balanced", "high"] = "balanced"
    pronunciation_rules: list[PronunciationRule] = Field(default_factory=list, max_length=100)

    @field_validator("pronunciation_rules")
    @classmethod
    def unique_pronunciations(cls, value: list[PronunciationRule]) -> list[PronunciationRule]:
        keys = [(rule.source, rule.language) for rule in value]
        if len(keys) != len(set(keys)):
            raise ValueError("같은 언어의 같은 단어는 한 번만 등록하세요.")
        return value


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
    pronunciation_rules: list[PronunciationRule] = Field(default_factory=list, max_length=100)

    @field_validator("pronunciation_rules")
    @classmethod
    def unique_pronunciations(cls, value: list[PronunciationRule]) -> list[PronunciationRule]:
        return ContentProductionSettings.unique_pronunciations(value)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Text is required")
        return cleaned


class GenerateResponse(BaseModel):
    text: str
    spoken_text: str | None = None
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
    sound_effect_generation: bool = False
    music_generation: bool = False


# A "domain" is a place in the studio where the user picks a model.
# New model kinds are added by mapping a capability flag to a domain here and in model_preferences.DOMAIN_CAPABILITY.
ModelDomain = Literal["voice", "music", "cover", "sfx"]
MODEL_DOMAINS: tuple[ModelDomain, ...] = ("voice", "music", "cover", "sfx")


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
    domains: list[ModelDomain] = Field(default_factory=list)
    homepage: str | None = None
    license: str | None = None
    platforms: list[str] = Field(default_factory=list)
    install_command: str | None = None


class ModelPreference(BaseModel):
    id: str
    enabled: bool = True
    order: int = 0


class ModelPreferencesUpdateRequest(BaseModel):
    model_preferences: dict[str, ModelPreference] = Field(default_factory=dict)
    default_tts_model: str | None = None
    default_vc_model: str | None = None
    default_models: dict[ModelDomain, str] = Field(default_factory=dict)


class ModelPreferencesResponse(BaseModel):
    model_preferences: dict[str, ModelPreference] = Field(default_factory=dict)
    default_tts_model: str
    default_vc_model: str
    default_models: dict[ModelDomain, str] = Field(default_factory=dict)


class ModelListResponse(BaseModel):
    models: list[RuntimeModelStatus]
    default_tts_model: str
    default_vc_model: str
    default_models: dict[ModelDomain, str] = Field(default_factory=dict)
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
    segment_type: Literal["speech", "sfx"] = "speech"
    speaker_name: str | None = None
    sfx_duration_seconds: float = Field(default=3.0, ge=0.5, le=30.0)

    @field_validator("text")
    @classmethod
    def segment_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Segment text is required")
        return cleaned


class SoundEffectGenerateRequest(BaseModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    asset_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    prompt: str
    negative_prompt: str = "speech, voice, music"
    duration_seconds: float | None = Field(default=None, ge=0.5, le=30.0)
    auto_duration: bool = True
    steps: int = Field(default=8, ge=1, le=16)
    guidance_scale: float = Field(default=3.0, ge=0.0, le=8.0)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    variations: int = Field(default=2, ge=1, le=4)
    progress_id: str | None = None
    model_id: str | None = Field(default=None, max_length=80)

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sound effect prompt is required")
        return cleaned

    @model_validator(mode="after")
    def require_project_and_asset_pair(self) -> "SoundEffectGenerateRequest":
        if bool(self.project_id) != bool(self.asset_id):
            raise ValueError("프로젝트와 사운드 ID를 함께 지정하세요.")
        if self.seed is not None and self.seed + self.variations - 1 > 2_147_483_647:
            raise ValueError("결과 수를 포함한 시드가 허용 범위를 넘습니다.")
        return self


class SoundEffectPromptPlan(BaseModel):
    source_prompt: str
    generation_prompt: str
    duration_seconds: float
    duration_mode: Literal["auto", "manual"]
    translated: bool
    planner: Literal["local-llm", "subscription-llm", "api-llm", "rules-fallback", "direct"]
    provider: str | None = None
    model: str | None = None


class SoundEffectResult(BaseModel):
    id: str
    prompt: str
    generation_prompt: str
    negative_prompt: str
    audio_url: str
    duration_seconds: float
    seed: int
    model_id: str = "stable-audio-sfx"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SoundEffectGenerateResponse(BaseModel):
    results: list[SoundEffectResult]
    plan: SoundEffectPromptPlan
    project: dict | None = None
    storage_warning: str | None = None
    generation_warning: str | None = None


class StoryStudioGenerateRequest(BaseModel):
    title: str = "새 대화 오디오"
    project_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[\w-]+$")
    progress_id: str | None = None
    default_model_id: str | None = None
    num_step: int = Field(default=32, ge=4, le=64)
    guidance_scale: float = Field(default=2.0, ge=0.0, le=10.0)
    denoise: bool = True
    normalize_output: bool = True
    segments: list[StorySegmentRequest] = Field(min_length=1, max_length=80)

    @field_validator("segments")
    @classmethod
    def segments_must_not_be_empty(cls, value: list[StorySegmentRequest]) -> list[StorySegmentRequest]:
        if not value:
            raise ValueError("At least one story segment is required")
        return value


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
    segment_type: Literal["speech", "sfx"] = "speech"
    speaker_name: str | None = None
    pause_after_ms: int = 0
    tone_prompt: str | None = None
    effective_instruct: str | None = None


class StoryStudioGenerateResponse(BaseModel):
    title: str
    audio_url: str
    duration_seconds: float
    segments: list[StorySegmentResult]
    source_segments: list[StorySegmentRequest] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StoryProjectSegment(StorySegmentRequest):
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(default="", max_length=60_000)
    translated_text: str | None = Field(default=None, max_length=60_000)

    @field_validator("text")
    @classmethod
    def segment_text_must_not_be_blank(cls, value: str) -> str:
        # Drafts may contain unfinished lines. Generation validates nonblank text separately.
        return value


class StoryProjectItem(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    title: str = Field(max_length=255)
    segments: list[StoryProjectSegment] = Field(min_length=1, max_length=80)
    result: StoryStudioGenerateResponse | None = None
    dialogue_format: Literal["deep-dive", "interview", "debate", "briefing"] | None = None
    source_text: str | None = Field(default=None, max_length=60_000)
    source_excerpt: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def segment_ids_must_be_unique(self) -> "StoryProjectItem":
        if len({segment.id for segment in self.segments}) != len(self.segments):
            raise ValueError("단락 ID는 서로 달라야 합니다.")
        return self


class DialogueDraftRequest(BaseModel):
    # source: 자료 원문 안에서만 대화를 만듭니다. topic: 한 줄 주제 요청으로 새 대화를 씁니다.
    mode: Literal["source", "topic"] = "source"
    source_text: str = Field(min_length=4, max_length=60_000)
    format: Literal["deep-dive", "interview", "debate", "briefing"] = "interview"
    language: Literal["ko", "en", "ja", "zh"] = "ko"
    speech_turns: int = Field(default=8, ge=4, le=18)
    include_sfx_cues: bool = False
    focus: str | None = Field(default=None, max_length=1000)
    speaker_a_name: str | None = Field(default=None, max_length=30)
    speaker_b_name: str | None = Field(default=None, max_length=30)
    speaker_c_name: str | None = Field(default=None, max_length=30)
    speaker_d_name: str | None = Field(default=None, max_length=30)

    @field_validator("source_text")
    @classmethod
    def source_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_text는 비워둘 수 없습니다.")
        if len(cleaned) > 60_000:
            raise ValueError("source_text는 공백을 제외하고 60000자를 넘을 수 없습니다.")
        return cleaned

    @field_validator("focus", "speaker_a_name", "speaker_b_name", "speaker_c_name", "speaker_d_name")
    @classmethod
    def optional_speaker_names_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @model_validator(mode="after")
    def source_text_must_be_long_enough_for_mode(self) -> "DialogueDraftRequest":
        if self.mode == "source" and len(self.source_text) < 20:
            raise ValueError("source_text는 공백을 제외하고 20자 이상이어야 합니다.")
        return self

    @model_validator(mode="after")
    def speaker_names_must_be_distinct(self) -> "DialogueDraftRequest":
        import re

        if self.speaker_d_name and not self.speaker_c_name:
            raise ValueError("네 번째 화자를 사용하려면 세 번째 화자 이름도 입력하세요.")
        defaults = {"ko": ("화자 A", "화자 B"), "en": ("Speaker A", "Speaker B"), "ja": ("話者 A", "話者 B"), "zh": ("说话者 A", "说话者 B")}
        names = [self.speaker_a_name or defaults[self.language][0], self.speaker_b_name or defaults[self.language][1]]
        names += [name for name in (self.speaker_c_name, self.speaker_d_name) if name]
        canonical = [re.sub(r"[\W_]+", "", name.casefold(), flags=re.UNICODE) for name in names]
        if any(not name for name in canonical) or len(set(canonical)) != len(canonical):
            raise ValueError("화자 이름은 서로 달라야 하며 문자나 숫자를 포함해야 합니다.")
        aliases = {"a": 0, "speakera": 0, "hosta": 0, "interviewera": 0, "b": 1, "speakerb": 1, "guestb": 1, "respondentb": 1, "intervieweeb": 1, "c": 2, "speakerc": 2, "d": 3, "speakerd": 3}
        if any(name in aliases and aliases[name] != index for index, name in enumerate(canonical)):
            raise ValueError("다른 화자의 A/B/C/D 표기와 겹치는 이름은 사용할 수 없습니다.")
        return self


class DialogueDraftSpeakers(BaseModel):
    speaker_a: str
    speaker_b: str


class DialogueDraftTurn(BaseModel):
    index: int
    speaker: Literal["A", "B", "C", "D"]
    text: str
    sfx_cue: str | None = None

    @field_validator("text")
    @classmethod
    def dialogue_turn_text_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Dialogue turn text is required")
        return cleaned

    @field_validator("sfx_cue")
    @classmethod
    def dialogue_turn_sfx_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DialogueDraftResponse(BaseModel):
    title: str
    summary: str
    format: Literal["deep-dive", "interview", "debate", "briefing"]
    language: Literal["ko", "en", "ja", "zh"]
    speech_turns: int
    include_sfx_cues: bool
    speakers: DialogueDraftSpeakers
    additional_speakers: dict[Literal["C", "D"], str] = Field(default_factory=dict)
    turns: list[DialogueDraftTurn]
    provider: str
    model: str


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
    conversion_options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    job_id: str | None = None
    created_at: datetime | None = None


class UploadedAudioResponse(BaseModel):
    audio_url: str
    filename: str


class MediaImportRequest(BaseModel):
    url: str
    isolate_voice: bool = False
    start_seconds: float | None = Field(default=None, ge=0, le=86400)
    end_seconds: float | None = Field(default=None, gt=0, le=86400)

    @field_validator("url")
    @classmethod
    def url_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Media URL is required")
        return cleaned


class MediaInfoRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Media URL is required")
        return cleaned


class MediaInfoResponse(BaseModel):
    platform: Literal["youtube", "instagram"]
    title: str
    webpage_url: str
    duration_seconds: float | None = None
    uploader: str | None = None
    max_duration_seconds: int


class MediaImportResponse(BaseModel):
    platform: Literal["youtube", "instagram"]
    title: str
    webpage_url: str
    duration_seconds: float | None = None
    audio_url: str
    filename: str
    voice_isolated: bool = False


class VoiceConversionJobItem(BaseModel):
    id: str
    model_id: str
    source_audio_url: str | None = None
    target_voice_id: str | None = None
    output_audio_url: str
    transcript: str | None = None
    created_at: datetime


class AudioAssetItem(BaseModel):
    id: str
    kind: Literal["registered-voice", "tts", "ai-cover", "dialogue", "sound-effect", "other"]
    title: str
    filename: str
    audio_url: str
    source_audio_url: str | None = None
    available: bool
    size_bytes: int | None = None
    duration_seconds: float | None = None
    voice_id: str | None = None
    voice_name: str | None = None
    model_id: str | None = None
    source_title: str | None = None
    transcript: str | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    created_at: datetime


class AudioAssetCatalogResponse(BaseModel):
    registered_voices: list[AudioAssetItem] = Field(default_factory=list)
    generated_files: list[AudioAssetItem] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptSegmentsResponse(BaseModel):
    segments: list[TranscriptSegment]
    text: str


class TranslateRequest(BaseModel):
    text: str = Field(max_length=60_000)
    languages: list[str] = Field(default_factory=lambda: ["en", "ja"], min_length=1, max_length=8)

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
        import re

        cleaned = list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))
        if not cleaned:
            raise ValueError("At least one target language is required")
        if any(not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", item) for item in cleaned):
            raise ValueError("대상 언어는 en, ja, zh-cn 같은 언어 코드로 지정하세요.")
        return cleaned


class TranslateResponse(BaseModel):
    source_text: str
    translations: dict[str, str]
    provider: str
    model: str


class AiTextSelectionRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=90)
    model_id: str = Field(min_length=1, max_length=255)

    @field_validator("provider_id")
    @classmethod
    def provider_id_must_be_supported(cls, value: str) -> str:
        from app.services.ai_api_profiles import valid_provider
        if not valid_provider(value):
            raise ValueError("지원하지 않는 AI 연결입니다.")
        return value

    @field_validator("model_id")
    @classmethod
    def model_id_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Model id is required")
        return cleaned


class AiTextConnectionUpdateRequest(BaseModel):
    local_only: bool | None = None
    translation_mode: Literal["auto", "apple", "selected"] | None = None
    provider_id: Literal["local", "nvidia", "compatible"] | None = None
    base_url: str | None = Field(default=None, max_length=2000)
    model_id: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=4096)


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
    spoken_text: str | None = None
    production_settings: ContentProductionSettings | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    source_language: str = Field(default='ko', min_length=1, max_length=32)
    source_text: str
    translations: dict[str, str] = Field(default_factory=dict)
    production_settings: ContentProductionSettings | None = None
    results: list[ContentResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentCreateRequest(BaseModel):
    source_language: str | None = Field(default=None, min_length=1, max_length=32)
    title: str
    source_text: str
    translations: dict[str, str] = Field(default_factory=dict)
    production_settings: ContentProductionSettings | None = None


class ContentUpdateRequest(BaseModel):
    source_language: str | None = Field(default=None, min_length=1, max_length=32)
    title: str | None = None
    source_text: str | None = None
    translations: dict[str, str] | None = None
    production_settings: ContentProductionSettings | None = None


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


class ScriptAssistRequest(BaseModel):
    mode: Literal["write", "polish", "shorten", "expand"]
    text: str = Field(default="", max_length=20_000)
    brief: str = Field(default="", max_length=2_000)
    tone: str = Field(default="", max_length=100)
    language: Literal["ko", "en", "ja", "zh"] = "ko"
    target_seconds: int | None = Field(default=None, ge=5, le=600)

    @model_validator(mode="after")
    def require_input_for_mode(self) -> "ScriptAssistRequest":
        self.text = self.text.strip()
        self.brief = self.brief.strip()
        self.tone = self.tone.strip()
        if self.mode == "write" and not (self.brief or self.text):
            raise ValueError("어떤 대본이 필요한지 한 줄 이상 적어 주세요.")
        if self.mode != "write" and not self.text:
            raise ValueError("다듬을 대본을 먼저 입력하세요.")
        return self


class ScriptAssistResponse(BaseModel):
    text: str
    chars: int
    estimated_seconds: int
    provider: str
    model: str