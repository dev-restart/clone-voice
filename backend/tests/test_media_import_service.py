from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.media_import_service import import_media_audio, inspect_media, media_dlp_common_options


class FakeYoutubeDL:
    calls: list[dict] = []
    duration = 45.0

    def __init__(self, options: dict):
        self.options = options
        self.calls.append(options)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url: str, download: bool):
        if download:
            Path(self.options["outtmpl"]).with_suffix(".wav").write_bytes(b"RIFF")
        return {
            "title": "테스트 Reel",
            "webpage_url": url,
            "duration": self.duration,
        }


def test_import_media_audio_downloads_instagram_audio_to_upload_storage(tmp_path: Path, monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.duration = 45.0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    settings = Settings(storage_dir=tmp_path / "storage")

    result = import_media_audio("https://www.instagram.com/reel/ABC_def-12/", settings)

    assert result.platform == "instagram"
    assert result.title == "테스트 Reel"
    assert result.duration_seconds == 45.0
    assert result.audio_path.is_file()
    assert result.audio_path.parent == settings.uploads_dir
    assert FakeYoutubeDL.calls[-1]["format"] == "bestaudio/best"
    assert FakeYoutubeDL.calls[-1]["noplaylist"] is True
    assert FakeYoutubeDL.calls[-1]["playlist_items"] == "1"


def test_import_media_audio_rejects_media_over_configured_duration(tmp_path: Path, monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.duration = 121.0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    settings = Settings(storage_dir=tmp_path / "storage", media_import_max_duration_seconds=120)

    with pytest.raises(RuntimeError, match="2분 이하"):
        import_media_audio("https://youtu.be/WuW8V7US-0o", settings)

    assert len(FakeYoutubeDL.calls) == 1


def test_media_import_options_reject_missing_cookie_file(tmp_path: Path):
    settings = Settings(storage_dir=tmp_path / "storage", media_import_cookie_file=tmp_path / "missing.txt")

    with pytest.raises(RuntimeError, match="cookie file"):
        media_dlp_common_options(settings)


class ForbiddenFirstYoutubeDL(FakeYoutubeDL):
    """기본 player client가 403을 돌려주는 상황을 흉내낸다."""

    def extract_info(self, url: str, download: bool):
        if download and "extractor_args" not in self.options:
            Path(self.options["outtmpl"]).with_suffix(".part").write_bytes(b"partial")
            raise RuntimeError("unable to download video data: HTTP Error 403: Forbidden")
        return super().extract_info(url, download)


def test_import_media_audio_retries_youtube_with_fallback_player_client(tmp_path: Path, monkeypatch):
    ForbiddenFirstYoutubeDL.calls = []
    ForbiddenFirstYoutubeDL.duration = 45.0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=ForbiddenFirstYoutubeDL))
    settings = Settings(storage_dir=tmp_path / "storage")

    result = import_media_audio("https://www.youtube.com/watch?v=_GcybkQzme0", settings)

    assert result.platform == "youtube"
    assert result.audio_path.is_file()
    assert ForbiddenFirstYoutubeDL.calls[-1]["extractor_args"] == {"youtube": {"player_client": ["web_embedded"]}}
    assert not list(settings.uploads_dir.glob("*.part"))


class FakeDownloadRanges:
    calls: list[tuple] = []

    @staticmethod
    def download_range_func(chapters, ranges):
        FakeDownloadRanges.calls.append((chapters, ranges))
        return ("ranges", tuple(ranges))


def test_import_media_audio_downloads_only_the_requested_clip(tmp_path: Path, monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.duration = 3 * 3600.0  # the whole video is far over the limit
    FakeDownloadRanges.calls = []
    monkeypatch.setitem(
        sys.modules,
        "yt_dlp",
        SimpleNamespace(YoutubeDL=FakeYoutubeDL, utils=SimpleNamespace(download_range_func=FakeDownloadRanges.download_range_func)),
    )
    settings = Settings(storage_dir=tmp_path / "storage", media_import_max_duration_seconds=3600)

    result = import_media_audio("https://youtu.be/WuW8V7US-0o", settings, start_seconds=60, end_seconds=180)

    assert FakeDownloadRanges.calls == [([], [(60.0, 180.0)])]
    assert FakeYoutubeDL.calls[-1]["force_keyframes_at_cuts"] is True
    assert result.duration_seconds == 120.0


def test_import_media_audio_rejects_a_clip_over_the_limit(tmp_path: Path, monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.duration = 3 * 3600.0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL, utils=SimpleNamespace(download_range_func=lambda *a: None)))
    settings = Settings(storage_dir=tmp_path / "storage", media_import_max_duration_seconds=120)

    with pytest.raises(RuntimeError, match="2분 이하"):
        import_media_audio("https://youtu.be/WuW8V7US-0o", settings, start_seconds=0, end_seconds=600)


def test_import_media_audio_rejects_an_inverted_clip(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    settings = Settings(storage_dir=tmp_path / "storage")

    with pytest.raises(RuntimeError, match="끝 시간"):
        import_media_audio("https://youtu.be/WuW8V7US-0o", settings, start_seconds=30, end_seconds=10)


def test_inspect_media_reports_title_and_duration_without_downloading(tmp_path: Path, monkeypatch):
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.duration = 95.0
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    settings = Settings(storage_dir=tmp_path / "storage", media_import_max_duration_seconds=600)

    info = inspect_media("https://www.youtube.com/watch?v=dQw4w9WgXcQ", settings)

    assert info.platform == "youtube"
    assert info.title == "테스트 Reel"
    assert info.duration_seconds == 95.0
    assert info.max_duration_seconds == 600
    assert not list(settings.uploads_dir.glob("*")) if settings.uploads_dir.exists() else True
