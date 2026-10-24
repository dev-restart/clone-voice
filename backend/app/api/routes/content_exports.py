import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from app.api.deps import get_content_store
from app.config import Settings, get_settings
from app.services.content_store import ContentStore

router = APIRouter()


@router.get("/api/contents/{content_id}/results/{result_id}/export")
def export_content_result(
    content_id: str,
    result_id: str,
    format: Literal["wav", "mp3", "zip", "txt"] = "zip",
    settings: Settings = Depends(get_settings),
    store: ContentStore = Depends(get_content_store),
):
    content = store.get(content_id)
    result = next((item for item in content.results if item.id == result_id), None) if content else None
    if content is None or result is None:
        raise HTTPException(status_code=404, detail="내려받을 생성 결과를 찾지 못했습니다.")
    filename = re.sub(r"[^\w가-힣 .-]", "_", content.title).strip(" .")[:70] or "voice"
    language_label = re.sub(r"[^\w-]", "_", result.language)[:20] or "audio"
    filename = f"{filename}-{language_label}-{result.id[:8]}"
    if format == "txt":
        from urllib.parse import quote

        return Response(
            content=result.text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename + '.txt')}"},
        )
    source = (settings.outputs_dir / Path(result.audio_url).name).resolve()
    if source.parent != settings.outputs_dir.resolve() or not source.is_file():
        raise HTTPException(status_code=404, detail="음성 파일이 없습니다. 대본을 다시 생성해 주세요.")
    if format == "wav" and source.suffix.lower() == ".wav":
        return FileResponse(source, media_type="audio/wav", filename=f"{filename}.wav")

    temporary = TemporaryDirectory(prefix="clone-voice-export-")
    destination = Path(temporary.name) / f"{filename}.{format}"
    try:
        if format in {"mp3", "wav"}:
            codec_options = ["-codec:a", "libmp3lame", "-b:a", "192k"] if format == "mp3" else ["-codec:a", "pcm_s16le"]
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn", *codec_options, str(destination)],
                check=True, capture_output=True, timeout=120,
            )
        else:
            with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
                archive.write(source, f"audio{source.suffix}")
                archive.writestr("script.txt", result.text)
                if result.spoken_text is not None:
                    archive.writestr("spoken-script.txt", result.spoken_text)
                archive.writestr("production.json", json.dumps({
                    "title": content.title,
                    "language": result.language,
                    "voice_name": result.voice_name,
                    "model_id": result.model_id,
                    "duration_seconds": result.duration_seconds,
                    "created_at": result.created_at.isoformat(),
                    "production_settings": result.production_settings.model_dump(mode="json") if result.production_settings else None,
                }, ensure_ascii=False, indent=2))
    except (OSError, subprocess.SubprocessError) as exc:
        temporary.cleanup()
        raise HTTPException(status_code=503, detail="내보내기에 실패했습니다. ffmpeg 설치와 저장 공간을 확인하세요.") from exc
    return FileResponse(
        destination,
        media_type={"mp3": "audio/mpeg", "wav": "audio/wav", "zip": "application/zip"}[format],
        filename=destination.name,
        background=BackgroundTask(temporary.cleanup),
    )
