import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from starlette.background import BackgroundTask
from starlette.responses import FileResponse


AudioExportFormat = Literal["mp3", "wav"]
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"}


class AudioExportError(RuntimeError):
    pass


def export_audio_file(source: Path, format: AudioExportFormat) -> FileResponse:
    # 수정이유: 같은 형식은 원본을 그대로 내려받아 WAV 정밀도와 MP3 음질을 보존합니다.
    if source.suffix.lower() == f".{format}":
        return FileResponse(
            source,
            media_type="audio/mpeg" if format == "mp3" else "audio/wav",
            filename=f"{source.stem}.{format}",
        )
    temporary = None
    try:
        temporary = TemporaryDirectory(prefix="clone-voice-audio-export-")
        destination = Path(temporary.name) / f"audio.{format}"
        codec = ["-codec:a", "libmp3lame", "-b:a", "192k"] if format == "mp3" else ["-codec:a", "pcm_s16le"]
        # 수정이유: 음악의 좌우 채널과 sample rate는 유지하고, 다운로드 사본의 형식만 바꿉니다.
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map", "0:a:0", "-vn", *codec, str(destination)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        if not destination.is_file() or destination.stat().st_size == 0:
            raise AudioExportError("내보낼 오디오 파일이 생성되지 않았습니다.")
        return FileResponse(
            destination,
            media_type="audio/mpeg" if format == "mp3" else "audio/wav",
            filename=f"{source.stem}.{format}",
            background=BackgroundTask(temporary.cleanup),
        )
    except (OSError, subprocess.SubprocessError, AudioExportError) as exc:
        if temporary is not None:
            temporary.cleanup()
        raise AudioExportError("오디오 내보내기에 실패했습니다. ffmpeg 설치와 저장 공간을 확인하세요.") from exc
