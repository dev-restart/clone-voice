from pathlib import Path

from app.config import Settings
from app.db.repositories import VoiceRepository
from app.db.session import session_scope
from app.schemas import VoiceProfile


class VoiceStore:
    def __init__(self, voices_dir: Path, settings: Settings | None = None):
        self.voices_dir = voices_dir
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings

    def list(self) -> list[VoiceProfile]:
        with session_scope(self.settings) as session:
            return VoiceRepository(session).list()

    def get(self, voice_id: str) -> VoiceProfile | None:
        with session_scope(self.settings) as session:
            return VoiceRepository(session).get(voice_id)

    def save(self, voice: VoiceProfile) -> VoiceProfile:
        with session_scope(self.settings) as session:
            return VoiceRepository(session).save(voice)

    def delete(self, voice_id: str) -> VoiceProfile | None:
        with session_scope(self.settings) as session:
            return VoiceRepository(session).delete(voice_id)
