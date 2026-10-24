from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.config import Settings
from app.db.repositories import ContentRepository
from app.db.session import session_scope
from app.schemas import ContentItem, ContentResult

# The local app runs one backend process. Keep read-modify-write transactions
# together; inference never holds this lock.
_content_lock = RLock()


class ContentStore:
    def __init__(self, contents_dir: Path, settings: Settings | None = None):
        self.contents_dir = contents_dir
        self.contents_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings

    def list(self) -> list[ContentItem]:
        with _content_lock, session_scope(self.settings) as session:
            return ContentRepository(session).list()

    def get(self, content_id: str) -> ContentItem | None:
        with _content_lock, session_scope(self.settings) as session:
            return ContentRepository(session).get(content_id)

    def save(self, content: ContentItem) -> ContentItem:
        content.updated_at = datetime.now(timezone.utc)
        with _content_lock, session_scope(self.settings) as session:
            return ContentRepository(session).save(content)

    def patch(self, content_id: str, changes: dict) -> ContentItem | None:
        allowed = {"title", "source_text", "source_language", "translations", "production_settings"}
        if set(changes) - allowed:
            raise ValueError("Only editable content fields can be patched")
        with _content_lock, session_scope(self.settings) as session:
            repository = ContentRepository(session)
            latest = repository.get(content_id)
            if latest is None:
                return None
            values = latest.model_dump()
            values.update(changes)
            updated = ContentItem.model_validate(values)
            return repository.save(updated)

    def append_results(self, content_id: str, results: list[ContentResult]) -> ContentItem | None:
        with _content_lock, session_scope(self.settings) as session:
            repository = ContentRepository(session)
            latest = repository.get(content_id)
            if latest is None:
                return None
            existing = {result.id for result in latest.results}
            additions = [result for result in results if result.id not in existing]
            latest.results = additions + latest.results
            return repository.save(latest)

    def remove_result(self, content_id: str, result_id: str) -> ContentItem | None:
        with _content_lock, session_scope(self.settings) as session:
            repository = ContentRepository(session)
            latest = repository.get(content_id)
            if latest is None:
                return None
            latest.results = [result for result in latest.results if result.id != result_id]
            return repository.save(latest)

    def delete(self, content_id: str) -> ContentItem | None:
        with _content_lock, session_scope(self.settings) as session:
            return ContentRepository(session).delete(content_id)
