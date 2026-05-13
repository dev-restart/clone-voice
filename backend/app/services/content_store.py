from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db.repositories import ContentRepository
from app.db.session import session_scope
from app.schemas import ContentItem


class ContentStore:
    def __init__(self, contents_dir: Path, settings: Settings | None = None):
        self.contents_dir = contents_dir
        self.contents_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings

    def list(self) -> list[ContentItem]:
        with session_scope(self.settings) as session:
            return ContentRepository(session).list()

    def get(self, content_id: str) -> ContentItem | None:
        with session_scope(self.settings) as session:
            return ContentRepository(session).get(content_id)

    def save(self, content: ContentItem) -> ContentItem:
        content.updated_at = datetime.now(timezone.utc)
        with session_scope(self.settings) as session:
            return ContentRepository(session).save(content)

    def delete(self, content_id: str) -> ContentItem | None:
        with session_scope(self.settings) as session:
            return ContentRepository(session).delete(content_id)
