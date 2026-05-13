from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.config import Settings
from app.services.audio_utils import isolate_speech_audio

_YOUTUBE_VIDEO_ID_PATTERN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


@dataclass(frozen=True)
class NormalizedYouTubeUrl:
    url: str
    video_id: str
    kind: Literal["video", "shorts"]


@dataclass(frozen=True)
class YouTubeAudioImport:
    title: str
    webpage_url: str
    duration_seconds: float | None
    audio_path: Path
    voice_isolated: bool = False


def youtube_dlp_common_options() -> dict:
    js_runtimes: dict[str, dict] = {}
    if node_path := shutil.which("node"):
        js_runtimes["node"] = {"path": node_path}
    elif bun_path := shutil.which("bun"):
        js_runtimes["bun"] = {"path": bun_path}
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "remote_components": {"ejs:github"},
    }
    if js_runtimes:
        options["js_runtimes"] = js_runtimes
    return options


def normalize_youtube_url(url: str) -> NormalizedYouTubeUrl:
    cleaned = url.strip()
    if not cleaned:
        raise RuntimeError("YouTube URL is required.")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path_parts = [part for part in parsed.path.split("/") if part]
    video_id: str | None = None
    kind: Literal["video", "shorts"] = "video"

    if host == "youtu.be":
        video_id = path_parts[0] if path_parts else None
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        first = path_parts[0].lower() if path_parts else ""
        if first == "watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif first == "shorts":
            kind = "shorts"
            video_id = path_parts[1] if len(path_parts) > 1 else None
        elif first in {"embed", "live", "v"}:
            video_id = path_parts[1] if len(path_parts) > 1 else None
    else:
        raise RuntimeError("지원하는 유튜브 주소만 사용할 수 있습니다. 일반 영상, Shorts, youtu.be 주소를 입력해 주세요.")

    video_id = (video_id or "").strip()
    if not _is_valid_youtube_video_id(video_id):
        raise RuntimeError("유튜브 영상 ID를 확인할 수 없습니다. watch?v= 또는 /shorts/ 주소를 다시 확인해 주세요.")

    canonical = f"https://www.youtube.com/shorts/{video_id}" if kind == "shorts" else f"https://www.youtube.com/watch?v={video_id}"
    return NormalizedYouTubeUrl(url=canonical, video_id=video_id, kind=kind)


def _is_valid_youtube_video_id(video_id: str) -> bool:
    return 6 <= len(video_id) <= 64 and all(char in _YOUTUBE_VIDEO_ID_PATTERN for char in video_id)


def import_youtube_audio(url: str, settings: Settings, isolate_voice: bool = False) -> YouTubeAudioImport:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("YouTube import requires yt-dlp. Run `uv add yt-dlp` in the backend directory.") from exc

    normalized = normalize_youtube_url(url)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    output_base = settings.uploads_dir / f"{job_id}-youtube"
    output_path = output_base.with_suffix(".wav")

    common_options = youtube_dlp_common_options()
    try:
        with yt_dlp.YoutubeDL(common_options) as ydl:
            info = ydl.extract_info(normalized.url, download=False)
    except Exception as exc:
        raise RuntimeError(f"YouTube metadata could not be loaded: {exc}") from exc

    duration = info.get("duration") if isinstance(info, dict) else None

    download_options = {
        **common_options,
        "format": "bestaudio/best",
        "outtmpl": str(output_base),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
    }
    try:
        with yt_dlp.YoutubeDL(download_options) as ydl:
            downloaded_info = ydl.extract_info(normalized.url, download=True)
    except Exception as exc:
        raise RuntimeError(f"YouTube audio could not be downloaded: {exc}") from exc

    if not output_path.exists():
        matches = sorted(settings.uploads_dir.glob(f"{job_id}-youtube*.wav"))
        if matches:
            output_path = matches[0]
    if not output_path.exists():
        raise RuntimeError("YouTube audio was downloaded but the converted WAV file was not found.")

    voice_isolated = False
    if isolate_voice:
        isolated_path = settings.uploads_dir / f"{job_id}-youtube-voice.wav"
        try:
            isolate_speech_audio(output_path, isolated_path)
            output_path = isolated_path
            voice_isolated = True
        except RuntimeError as exc:
            raise RuntimeError(f"YouTube audio was downloaded, but speech-only cleanup failed: {exc}") from exc

    title = str(downloaded_info.get("title") or info.get("title") or "YouTube audio").strip()
    webpage_url = str(downloaded_info.get("webpage_url") or info.get("webpage_url") or normalized.url)
    duration_seconds = downloaded_info.get("duration") or duration
    return YouTubeAudioImport(
        title=title,
        webpage_url=webpage_url,
        duration_seconds=float(duration_seconds) if duration_seconds is not None else None,
        audio_path=output_path,
        voice_isolated=voice_isolated,
    )
