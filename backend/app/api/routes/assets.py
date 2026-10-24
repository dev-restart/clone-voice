from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import soundfile as sf
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import get_content_store, get_voice_store
from app.config import Settings, get_settings
from app.db.models import DbConversionJob
from app.db.session import session_scope
from app.schemas import AudioAssetCatalogResponse, AudioAssetItem
from app.services.content_store import ContentStore
from app.services.voice_store import VoiceStore
from app.services.story_project_store import StoryProjectStore

router = APIRouter()

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
_BUCKET_DIRS = {
    "voices": "voices_dir",
    "outputs": "outputs_dir",
    "uploads": "uploads_dir",
}


def _bucket_base(bucket: str, settings: Settings) -> Path:
    return getattr(settings, _BUCKET_DIRS[bucket]).resolve()


def _resolve_public_file(url: str | None, settings: Settings) -> Path | None:
    if not url:
        return None
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "files":
        return None
    bucket, filename = parts[2], parts[3]
    if bucket not in _BUCKET_DIRS or not filename:
        return None
    base = _bucket_base(bucket, settings)
    target = (base / filename).resolve()
    if target.parent != base:
        return None
    return target


def _stat_audio(
    url: str | None, settings: Settings
) -> tuple[bool, int | None, float | None, Path | None]:
    path = _resolve_public_file(url, settings)
    if path is None or not path.exists() or not path.is_file():
        return False, None, None, path
    duration_seconds: float | None = None
    try:
        duration_seconds = float(sf.info(path).duration)
    except RuntimeError:
        duration_seconds = None
    return True, path.stat().st_size, duration_seconds, path


def _display_name(path: Path | None, fallback: str) -> str:
    if path is None:
        return fallback
    return path.stem or fallback


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/api/assets", response_model=AudioAssetCatalogResponse)
def list_audio_assets(
    settings: Settings = Depends(get_settings),
    voice_store: VoiceStore = Depends(get_voice_store),
    content_store: ContentStore = Depends(get_content_store),
):
    registered_voices: list[AudioAssetItem] = []
    generated_files: list[AudioAssetItem] = []
    seen_generated_urls: set[str] = set()
    voices = voice_store.list()

    for voice in voices:
        available, size_bytes, duration_seconds, audio_path = _stat_audio(
            voice.audio_url, settings
        )
        source_path = _resolve_public_file(voice.source_audio_url, settings)
        registered_voices.append(
            AudioAssetItem(
                id=voice.id,
                kind="registered-voice",
                title=voice.name,
                filename=audio_path.name
                if audio_path
                else Path(voice.audio_url or voice.id).name or f"{voice.id}.wav",
                audio_url=voice.audio_url,
                source_audio_url=voice.source_audio_url,
                available=available,
                size_bytes=size_bytes,
                duration_seconds=duration_seconds,
                voice_id=voice.id,
                voice_name=voice.name,
                source_title=_display_name(source_path, "원본 샘플"),
                transcript=voice.transcript,
                trim_start=voice.trim_start,
                trim_end=voice.trim_end,
                created_at=_utc_datetime(voice.created_at),
            )
        )

    for content in content_store.list():
        for result in content.results:
            if result.audio_url in seen_generated_urls:
                continue
            seen_generated_urls.add(result.audio_url)
            available, size_bytes, duration_seconds, audio_path = _stat_audio(
                result.audio_url, settings
            )
            generated_files.append(
                AudioAssetItem(
                    id=result.id,
                    kind="tts",
                    title=content.title,
                    filename=audio_path.name
                    if audio_path
                    else Path(result.audio_url).name,
                    audio_url=result.audio_url,
                    available=available,
                    size_bytes=size_bytes,
                    duration_seconds=result.duration_seconds
                    if result.duration_seconds is not None
                    else duration_seconds,
                    voice_id=result.voice_id,
                    voice_name=result.voice_name,
                    model_id=result.model_id,
                    source_title=content.title,
                    transcript=result.text,
                    created_at=_utc_datetime(result.created_at),
                )
            )

    voice_lookup = {voice.id: voice.name for voice in voices}
    with session_scope(settings) as session:
        jobs = session.scalars(
            select(DbConversionJob)
            .order_by(DbConversionJob.created_at.desc())
            .limit(200)
        ).all()
    for row in jobs:
        if row.output_audio_url in seen_generated_urls:
            continue
        seen_generated_urls.add(row.output_audio_url)
        available, size_bytes, duration_seconds, audio_path = _stat_audio(
            row.output_audio_url, settings
        )
        source_path = Path(row.source_audio_path) if row.source_audio_path else None
        source_title = _display_name(source_path, "원곡")
        source_audio_url = None
        if source_path is not None:
            resolved_uploads = settings.uploads_dir.resolve()
            try:
                if source_path.resolve().parent == resolved_uploads:
                    source_audio_url = f"/api/files/uploads/{source_path.name}"
            except FileNotFoundError:
                source_audio_url = None
        generated_files.append(
            AudioAssetItem(
                id=row.id,
                kind="ai-cover",
                title=f"{voice_lookup.get(row.target_voice_id, '알 수 없는 목소리')} AI 커버",
                filename=audio_path.name
                if audio_path
                else Path(row.output_audio_url).name,
                audio_url=row.output_audio_url,
                source_audio_url=source_audio_url,
                available=available,
                size_bytes=size_bytes,
                duration_seconds=duration_seconds,
                voice_id=row.target_voice_id,
                voice_name=voice_lookup.get(row.target_voice_id),
                model_id=row.model_id,
                source_title=source_title,
                transcript=row.transcript,
                created_at=_utc_datetime(row.created_at),
            )
        )

    for project in StoryProjectStore(settings).list():
        if project.result is None:
            continue
        result = project.result
        if result.audio_url in seen_generated_urls:
            continue
        seen_generated_urls.add(result.audio_url)
        available, size_bytes, duration_seconds, audio_path = _stat_audio(result.audio_url, settings)
        voice_names = list(dict.fromkeys(segment.voice_name for segment in result.segments if segment.segment_type == "speech" and segment.voice_name))
        generated_files.append(AudioAssetItem(
            id=f"dialogue:{project.id}", kind="dialogue", title=result.title,
            filename=audio_path.name if audio_path else Path(result.audio_url).name,
            audio_url=result.audio_url, available=available, size_bytes=size_bytes,
            duration_seconds=result.duration_seconds or duration_seconds,
            voice_name=", ".join(voice_names) or None, source_title=project.title,
            transcript="\n".join(segment.text for segment in result.segments if segment.segment_type == "speech"),
            created_at=result.created_at,
        ))

    outputs_dir = settings.outputs_dir.resolve()
    for path in sorted(
        outputs_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True
    ):
        if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        audio_url = f"/api/files/outputs/{path.name}"
        if audio_url in seen_generated_urls:
            continue
        seen_generated_urls.add(audio_url)
        available, size_bytes, duration_seconds, _ = _stat_audio(audio_url, settings)
        kind = (
            "sound-effect"
            if path.stem.endswith("-sfx") or "sfx" in path.stem.lower()
            else "other"
        )
        generated_files.append(
            AudioAssetItem(
                id=f"orphan:{path.name}",
                kind=kind,
                title=path.stem,
                filename=path.name,
                audio_url=audio_url,
                available=available,
                size_bytes=size_bytes,
                duration_seconds=duration_seconds,
                created_at=datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ),
            )
        )

    registered_voices.sort(key=lambda item: item.created_at, reverse=True)
    generated_files.sort(key=lambda item: item.created_at, reverse=True)
    return AudioAssetCatalogResponse(
        registered_voices=registered_voices, generated_files=generated_files
    )
