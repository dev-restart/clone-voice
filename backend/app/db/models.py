from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DbVoice(Base):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="custom", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    avatar: Mapped[str | None] = mapped_column(String(255))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    samples: Mapped[list["DbVoiceSample"]] = relationship(
        back_populates="voice",
        cascade="all, delete-orphan",
        order_by="desc(DbVoiceSample.created_at)",
    )


class DbVoiceSample(Base):
    __tablename__ = "voice_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    voice_id: Mapped[str] = mapped_column(ForeignKey("voices.id", ondelete="CASCADE"), index=True, nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_audio_path: Mapped[str | None] = mapped_column(Text)
    source_audio_url: Mapped[str | None] = mapped_column(Text)
    trim_start: Mapped[float | None] = mapped_column(Float)
    trim_end: Mapped[float | None] = mapped_column(Float)
    sample_rate: Mapped[int] = mapped_column(default=24000, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    voice: Mapped[DbVoice] = relationship(back_populates="samples")


class DbContent(Base):
    __tablename__ = "contents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translations: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    results: Mapped[list["DbGenerationResult"]] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="desc(DbGenerationResult.created_at)",
    )


class DbGenerationResult(Base):
    __tablename__ = "generation_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    voice_id: Mapped[str | None] = mapped_column(String(64))
    voice_name: Mapped[str | None] = mapped_column(String(255))
    model_id: Mapped[str | None] = mapped_column(String(80))
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    tone_prompt: Mapped[str | None] = mapped_column(Text)
    style_prompt: Mapped[str | None] = mapped_column(Text)
    effective_instruct: Mapped[str | None] = mapped_column(Text)
    language_hint: Mapped[str | None] = mapped_column(String(80))
    accent_hint: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    content: Mapped[DbContent] = relationship(back_populates="results")


class DbSttJob(Base):
    __tablename__ = "stt_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_audio_path: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), default="whisper", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DbConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_voice_id: Mapped[str | None] = mapped_column(String(64))
    output_audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DbStudioSetting(Base):
    __tablename__ = "studio_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
