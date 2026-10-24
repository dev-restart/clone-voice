from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import DbContent, DbGenerationResult, DbStudioSetting, DbVoice, DbVoiceSample
from app.schemas import ContentItem, ContentResult, VoiceProfile


def _voice_to_schema(row: DbVoice) -> VoiceProfile:
    sample = row.samples[0] if row.samples else None
    return VoiceProfile(
        id=row.id,
        name=row.name,
        transcript=sample.transcript if sample else None,
        audio_path=sample.audio_path if sample else "",
        audio_url=sample.audio_url if sample else "",
        source_audio_path=sample.source_audio_path if sample else None,
        source_audio_url=sample.source_audio_url if sample else None,
        trim_start=sample.trim_start if sample else None,
        trim_end=sample.trim_end if sample else None,
        created_at=row.created_at,
        kind=row.kind,
        description=row.description,
        language=row.language,
        avatar=row.avatar,
        is_default=row.is_default,
        tags=row.tags or [],
    )


def _result_to_schema(row: DbGenerationResult, metadata: dict | None = None) -> ContentResult:
    metadata = metadata or {}
    return ContentResult(
        id=row.id,
        language=row.language,
        text=row.text,
        voice_id=row.voice_id,
        voice_name=row.voice_name,
        model_id=row.model_id,
        audio_url=row.audio_url,
        duration_seconds=row.duration_seconds,
        tone_prompt=row.tone_prompt,
        style_prompt=row.style_prompt,
        effective_instruct=row.effective_instruct,
        language_hint=row.language_hint,
        accent_hint=row.accent_hint,
        spoken_text=metadata.get("spoken_text"),
        production_settings=metadata.get("production_settings"),
        created_at=row.created_at,
    )


def _content_to_schema(row: DbContent, metadata: dict | None = None) -> ContentItem:
    metadata = metadata or {}
    return ContentItem(
        id=row.id,
        title=row.title,
        source_text=row.source_text,
        source_language=metadata.get('source_language') or (metadata.get('production_settings') or {}).get('language', 'ko'),
        translations=row.translations or {},
        production_settings=metadata.get("production_settings"),
        results=[_result_to_schema(result, metadata.get("results", {}).get(result.id)) for result in row.results],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class VoiceRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[VoiceProfile]:
        rows = self.session.scalars(
            select(DbVoice).options(selectinload(DbVoice.samples)).order_by(DbVoice.created_at.desc())
        ).all()
        return [_voice_to_schema(row) for row in rows if row.samples or row.kind == "preset"]

    def get(self, voice_id: str) -> VoiceProfile | None:
        row = self.session.scalar(
            select(DbVoice).where(DbVoice.id == voice_id).options(selectinload(DbVoice.samples))
        )
        return _voice_to_schema(row) if row else None

    def save(self, voice: VoiceProfile) -> VoiceProfile:
        row = self.session.get(DbVoice, voice.id)
        if row is None:
            row = DbVoice(id=voice.id, created_at=voice.created_at)
            self.session.add(row)
        row.name = voice.name
        row.kind = voice.kind
        row.description = voice.description
        row.language = voice.language
        row.avatar = voice.avatar
        row.is_default = voice.is_default
        row.tags = voice.tags

        sample = self.session.get(DbVoiceSample, voice.id)
        if sample is None:
            sample = DbVoiceSample(id=voice.id, voice_id=voice.id, created_at=voice.created_at)
            self.session.add(sample)
        sample.transcript = voice.transcript
        sample.audio_path = voice.audio_path
        sample.audio_url = voice.audio_url
        sample.source_audio_path = voice.source_audio_path
        sample.source_audio_url = voice.source_audio_url
        sample.trim_start = voice.trim_start
        sample.trim_end = voice.trim_end
        self.session.flush()
        return self.get(voice.id) or voice

    def delete(self, voice_id: str) -> VoiceProfile | None:
        target = self.get(voice_id)
        row = self.session.get(DbVoice, voice_id)
        if row is None:
            return None
        self.session.delete(row)
        self.session.flush()
        return target


class ContentRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[ContentItem]:
        rows = self.session.scalars(
            select(DbContent).options(selectinload(DbContent.results)).order_by(DbContent.updated_at.desc())
        ).all()
        keys = [self._settings_key(row.id) for row in rows]
        metadata = {
            item.key: item.value
            for item in self.session.scalars(select(DbStudioSetting).where(DbStudioSetting.key.in_(keys))).all()
        } if keys else {}
        return [_content_to_schema(row, metadata.get(self._settings_key(row.id))) for row in rows]

    @staticmethod
    def _settings_key(content_id: str) -> str:
        # Keep production metadata in the existing JSON settings table so older
        # local databases remain readable without a destructive schema rebuild.
        return f"content-production:{content_id}"

    def get(self, content_id: str) -> ContentItem | None:
        row = self.session.scalar(
            select(DbContent).where(DbContent.id == content_id).options(selectinload(DbContent.results))
        )
        metadata = StudioSettingsRepository(self.session).get(self._settings_key(content_id))
        return _content_to_schema(row, metadata) if row else None

    def save(self, content: ContentItem) -> ContentItem:
        now = datetime.now(timezone.utc)
        row = self.session.get(DbContent, content.id)
        if row is None:
            row = DbContent(id=content.id, created_at=content.created_at)
            self.session.add(row)
        row.title = content.title
        row.source_text = content.source_text
        row.translations = content.translations
        row.updated_at = now

        keep_ids = {result.id for result in content.results}
        for existing in list(row.results):
            if existing.id not in keep_ids:
                self.session.delete(existing)
        for result in content.results:
            result_row = self.session.get(DbGenerationResult, result.id)
            if result_row is None:
                result_row = DbGenerationResult(id=result.id, content_id=content.id, created_at=result.created_at)
                self.session.add(result_row)
            result_row.language = result.language
            result_row.text = result.text
            result_row.voice_id = result.voice_id
            result_row.voice_name = result.voice_name
            result_row.model_id = result.model_id
            result_row.audio_url = result.audio_url
            result_row.duration_seconds = result.duration_seconds
            result_row.tone_prompt = result.tone_prompt
            result_row.style_prompt = result.style_prompt
            result_row.effective_instruct = result.effective_instruct
            result_row.language_hint = result.language_hint
            result_row.accent_hint = result.accent_hint
        StudioSettingsRepository(self.session).set(self._settings_key(content.id), {
            "source_language": content.source_language,
            "production_settings": content.production_settings.model_dump(mode="json") if content.production_settings else None,
            "results": {
                result.id: {
                    "spoken_text": result.spoken_text,
                    "production_settings": result.production_settings.model_dump(mode="json") if result.production_settings else None,
                }
                for result in content.results
                if result.spoken_text is not None or result.production_settings is not None
            },
        })
        self.session.flush()
        self.session.expire(row, ["results"])
        return self.get(content.id) or content

    def delete(self, content_id: str) -> ContentItem | None:
        target = self.get(content_id)
        row = self.session.get(DbContent, content_id)
        if row is None:
            return None
        self.session.delete(row)
        metadata = self.session.get(DbStudioSetting, self._settings_key(content_id))
        if metadata is not None:
            self.session.delete(metadata)
        self.session.flush()
        return target


class StudioSettingsRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str) -> dict | None:
        row = self.session.get(DbStudioSetting, key)
        return dict(row.value or {}) if row else None

    def set(self, key: str, value: dict) -> dict:
        row = self.session.get(DbStudioSetting, key)
        if row is None:
            row = DbStudioSetting(key=key)
            self.session.add(row)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return dict(row.value or {})