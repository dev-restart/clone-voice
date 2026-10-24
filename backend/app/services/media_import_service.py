from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any, Callable, Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.config import Settings
from app.i18n import tr
from app.services.audio_utils import isolate_speech_audio

MediaPlatform = Literal["youtube", "instagram"]
MediaKind = Literal["video", "shorts", "post", "reel"]
_MEDIA_ID_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


@dataclass(frozen=True)
class NormalizedMediaUrl:
    url: str
    platform: MediaPlatform
    media_id: str
    kind: MediaKind


@dataclass(frozen=True)
class MediaAudioImport:
    platform: MediaPlatform
    title: str
    webpage_url: str
    duration_seconds: float | None
    audio_path: Path
    voice_isolated: bool = False


@dataclass(frozen=True)
class MediaInfo:
    platform: MediaPlatform
    title: str
    webpage_url: str
    duration_seconds: float | None
    uploader: str | None
    max_duration_seconds: int


def media_dlp_common_options(settings: Settings) -> dict:
    js_runtimes: dict[str, dict] = {}
    if node_path := shutil.which("node"):
        js_runtimes["node"] = {"path": node_path}

    options: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
    }
    if js_runtimes:
        options["js_runtimes"] = js_runtimes
    if settings.media_import_cookie_file:
        cookie_file = settings.media_import_cookie_file.expanduser()
        if not cookie_file.is_file():
            raise RuntimeError(tr(f"설정한 cookie file을 찾을 수 없습니다: {cookie_file}", f"The configured cookie file was not found: {cookie_file}"))
        options["cookiefile"] = str(cookie_file)
    return options


# YouTube가 기본 player client의 형식을 403으로 거부할 때 차례로 다시 시도할 client 목록.
_YOUTUBE_FALLBACK_PLAYER_CLIENTS = ("web_embedded", "tv_simply", "mweb")


def _client_option_variants(platform: MediaPlatform) -> list[dict]:
    if platform != "youtube":
        return [{}]
    return [
        {},
        *(
            {"extractor_args": {"youtube": {"player_client": [client]}}}
            for client in _YOUTUBE_FALLBACK_PLAYER_CLIENTS
        ),
    ]


def _clip_options(yt_dlp, clip: tuple[float, float | None] | None) -> dict:
    if clip is None:
        return {}
    start, end = clip
    return {
        "download_ranges": yt_dlp.utils.download_range_func([], [(start, end if end is not None else float("inf"))]),
        "force_keyframes_at_cuts": True,
    }


def _remove_partial_downloads(uploads_dir: Path, job_id: str) -> None:
    for leftover in uploads_dir.glob(f"{job_id}-*"):
        leftover.unlink(missing_ok=True)


def _extract_with_client_fallback(
    yt_dlp,
    normalized: NormalizedMediaUrl,
    options: dict,
    download: bool,
    on_retry: Callable[[], None] | None = None,
) -> Any:
    last_error: Exception | None = None
    for index, extra_options in enumerate(_client_option_variants(normalized.platform)):
        if index and on_retry is not None:
            on_retry()
        try:
            with yt_dlp.YoutubeDL({**options, **extra_options}) as ydl:
                return ydl.extract_info(normalized.url, download=download)
        except Exception as exc:  # 다음 player client로 다시 시도한다.
            last_error = exc
    raise last_error if last_error is not None else RuntimeError(tr("미디어 정보를 가져오지 못했습니다.", "Could not get the media information."))


def normalize_media_url(url: str) -> NormalizedMediaUrl:
    cleaned = url.strip()
    if not cleaned:
        raise RuntimeError(tr("YouTube 또는 Instagram 주소를 입력해 주세요.", "Enter a YouTube or Instagram link."))
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(tr("주소의 port 형식을 확인해 주세요.", "Check the port in the address.")) from exc
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or port:
        raise RuntimeError(tr("일반적인 HTTPS YouTube 또는 Instagram 주소만 사용할 수 있습니다.", "Only regular HTTPS YouTube or Instagram links can be used."))

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"youtu.be", "youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        return _normalize_youtube_url(host, path_parts, parsed.query)
    if host in {"instagram.com", "m.instagram.com"}:
        return _normalize_instagram_url(path_parts)
    raise RuntimeError(tr("YouTube와 Instagram의 단일 영상 주소만 사용할 수 있습니다.", "Only single YouTube or Instagram video links can be used."))


def _normalize_youtube_url(host: str, path_parts: list[str], query: str) -> NormalizedMediaUrl:
    media_id: str | None = None
    kind: MediaKind = "video"
    if host == "youtu.be":
        media_id = path_parts[0] if path_parts else None
    else:
        first = path_parts[0].lower() if path_parts else ""
        if first == "watch":
            media_id = parse_qs(query).get("v", [None])[0]
        elif first == "shorts":
            kind = "shorts"
            media_id = path_parts[1] if len(path_parts) > 1 else None
        elif first in {"embed", "live", "v"}:
            media_id = path_parts[1] if len(path_parts) > 1 else None

    media_id = (media_id or "").strip()
    if not _is_valid_media_id(media_id):
        raise RuntimeError(tr("YouTube 영상 ID를 확인할 수 없습니다. 단일 영상 또는 Shorts 주소를 확인해 주세요.", "Could not read the YouTube video ID. Use a single video or Shorts link."))
    canonical = f"https://www.youtube.com/shorts/{media_id}" if kind == "shorts" else f"https://www.youtube.com/watch?v={media_id}"
    return NormalizedMediaUrl(url=canonical, platform="youtube", media_id=media_id, kind=kind)


def _normalize_instagram_url(path_parts: list[str]) -> NormalizedMediaUrl:
    route = path_parts[0].lower() if path_parts else ""
    media_id = path_parts[1] if len(path_parts) > 1 else ""
    route_kind: dict[str, MediaKind] = {"p": "post", "reel": "reel", "reels": "reel", "tv": "video"}
    kind = route_kind.get(route)
    if kind is None or not _is_valid_media_id(media_id):
        raise RuntimeError(tr("Instagram 단일 게시물 또는 Reel 주소를 확인해 주세요. 프로필과 collection 주소는 지원하지 않습니다.", "Use a single Instagram post or Reel link. Profile and collection links are not supported."))
    canonical_route = "reel" if kind == "reel" else route
    canonical = f"https://www.instagram.com/{canonical_route}/{media_id}/"
    return NormalizedMediaUrl(url=canonical, platform="instagram", media_id=media_id, kind=kind)


def _is_valid_media_id(media_id: str) -> bool:
    return 5 <= len(media_id) <= 64 and all(char in _MEDIA_ID_CHARACTERS for char in media_id)


def _platform_label(platform: MediaPlatform) -> str:
    return "YouTube" if platform == "youtube" else "Instagram"


def inspect_media(url: str, settings: Settings) -> MediaInfo:
    """Look up title and length without downloading, so the UI can confirm a link before importing it."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(tr("미디어 가져오기에 필요한 yt-dlp가 설치되지 않았습니다. `pnpm run setup`을 다시 실행하세요.", "yt-dlp, which media import needs, is not installed. Run ./install.sh again.")) from exc

    normalized = normalize_media_url(url)
    label = _platform_label(normalized.platform)
    try:
        info = _extract_with_client_fallback(yt_dlp, normalized, media_dlp_common_options(settings), download=False)
    except Exception as exc:
        raise RuntimeError(tr(f"{label} 정보를 불러오지 못했습니다. 공개 게시물인지 확인해 주세요. ({exc})", f"Could not load the {label} information. Check that the post is public. ({exc})")) from exc
    if not isinstance(info, dict):
        raise RuntimeError(tr(f"{label} 게시물 정보를 확인하지 못했습니다.", f"Could not read the {label} post information."))
    duration = info.get("duration")
    return MediaInfo(
        platform=normalized.platform,
        title=str(info.get("title") or f"{label} audio").strip(),
        webpage_url=str(info.get("webpage_url") or normalized.url),
        duration_seconds=float(duration) if duration is not None else None,
        uploader=str(info.get("uploader") or info.get("channel") or "").strip() or None,
        max_duration_seconds=settings.media_import_max_duration_seconds,
    )


def _validated_range(start_seconds: float | None, end_seconds: float | None) -> tuple[float, float | None] | None:
    if start_seconds is None and end_seconds is None:
        return None
    start = float(start_seconds or 0)
    if start < 0:
        raise RuntimeError(tr("시작 시간은 0초 이상이어야 합니다.", "The start time must be 0 seconds or more."))
    if end_seconds is not None and float(end_seconds) <= start:
        raise RuntimeError(tr("끝 시간은 시작 시간보다 커야 합니다.", "The end time must be later than the start time."))
    return start, (float(end_seconds) if end_seconds is not None else None)


def import_media_audio(
    url: str,
    settings: Settings,
    isolate_voice: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> MediaAudioImport:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(tr("미디어 가져오기에 필요한 yt-dlp가 설치되지 않았습니다. `pnpm run setup`을 다시 실행하세요.", "yt-dlp, which media import needs, is not installed. Run ./install.sh again.")) from exc

    normalized = normalize_media_url(url)
    platform_label = _platform_label(normalized.platform)
    clip = _validated_range(start_seconds, end_seconds)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    output_base = settings.uploads_dir / f"{job_id}-{normalized.platform}"
    output_path = output_base.with_suffix(".wav")
    common_options = media_dlp_common_options(settings)

    try:
        info = _extract_with_client_fallback(yt_dlp, normalized, common_options, download=False)
    except Exception as exc:
        raise RuntimeError(tr(f"{platform_label} 정보를 불러오지 못했습니다. 공개 게시물인지 확인해 주세요. ({exc})", f"Could not load the {platform_label} information. Check that the post is public. ({exc})")) from exc

    if not isinstance(info, dict):
        raise RuntimeError(tr(f"{platform_label} 게시물 정보를 확인하지 못했습니다.", f"Could not read the {platform_label} post information."))
    duration = info.get("duration")
    # A chosen clip is what gets downloaded, so the limit applies to the clip rather than the whole video.
    effective_duration = duration
    if clip is not None:
        clip_end = clip[1] if clip[1] is not None else (float(duration) if duration is not None else None)
        if duration is not None and clip_end is not None:
            clip_end = min(clip_end, float(duration))
        if clip_end is not None:
            if clip_end <= clip[0]:
                raise RuntimeError(tr("선택한 구간이 영상 길이를 벗어났습니다.", "The selected range is outside the video."))
            effective_duration = clip_end - clip[0]
    if effective_duration is not None and float(effective_duration) > settings.media_import_max_duration_seconds:
        limit_minutes = settings.media_import_max_duration_seconds // 60
        raise RuntimeError(tr(f"{limit_minutes}분 이하의 영상만 가져올 수 있습니다.", f"Only videos of {limit_minutes} minutes or less can be imported."))

    download_options = {
        **common_options,
        "format": "bestaudio/best",
        "outtmpl": str(output_base),
        **_clip_options(yt_dlp, clip),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
    }
    try:
        downloaded_info = _extract_with_client_fallback(
            yt_dlp,
            normalized,
            download_options,
            download=True,
            on_retry=lambda: _remove_partial_downloads(settings.uploads_dir, job_id),
        )
    except Exception as exc:
        raise RuntimeError(tr(f"{platform_label} 오디오를 내려받지 못했습니다. ({exc})", f"Could not download the {platform_label} audio. ({exc})")) from exc

    if not output_path.exists():
        matches = sorted(settings.uploads_dir.glob(f"{job_id}-{normalized.platform}*.wav"))
        if matches:
            output_path = matches[0]
    if not output_path.exists():
        raise RuntimeError(tr(f"{platform_label} 오디오는 내려받았지만 변환된 WAV 파일을 찾지 못했습니다.", f"Downloaded the {platform_label} audio but could not find the converted WAV file."))

    voice_isolated = False
    if isolate_voice:
        isolated_path = settings.uploads_dir / f"{job_id}-{normalized.platform}-voice.wav"
        try:
            isolate_speech_audio(output_path, isolated_path)
            output_path.unlink(missing_ok=True)
            output_path = isolated_path
            voice_isolated = True
        except RuntimeError as exc:
            raise RuntimeError(tr(f"{platform_label} 오디오는 저장했지만 말소리 정리에 실패했습니다. ({exc})", f"Saved the {platform_label} audio but voice cleanup failed. ({exc})")) from exc

    downloaded_info = downloaded_info if isinstance(downloaded_info, dict) else {}
    title = str(downloaded_info.get("title") or info.get("title") or f"{platform_label} audio").strip()
    webpage_url = str(downloaded_info.get("webpage_url") or info.get("webpage_url") or normalized.url)
    duration_seconds = downloaded_info.get("duration") or duration
    if effective_duration is not None and clip is not None:
        duration_seconds = effective_duration
    return MediaAudioImport(
        platform=normalized.platform,
        title=title,
        webpage_url=webpage_url,
        duration_seconds=float(duration_seconds) if duration_seconds is not None else None,
        audio_path=output_path,
        voice_isolated=voice_isolated,
    )
