from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.schemas import ContentItem, VoiceProfile
from app.services.content_store import ContentStore
from app.services.voice_store import VoiceStore


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8") or "[]")


def main() -> None:
    settings = get_settings()
    voice_store = VoiceStore(settings.voices_dir, settings)
    content_store = ContentStore(settings.contents_dir, settings)

    voices_path = settings.voices_dir / "voices.json"
    contents_path = settings.contents_dir / "contents.json"

    voice_count = 0
    for payload in load_json(voices_path):
        voice_store.save(VoiceProfile.model_validate(payload))
        voice_count += 1

    content_count = 0
    for payload in load_json(contents_path):
        content_store.save(ContentItem.model_validate(payload))
        content_count += 1

    print(f"Migrated {voice_count} voices and {content_count} contents into {settings.resolved_database_url}")


if __name__ == "__main__":
    main()
