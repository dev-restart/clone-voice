from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.services.audio_export import AudioExportError, AudioExportFormat, SUPPORTED_AUDIO_EXTENSIONS, export_audio_file

router = APIRouter()


@router.get("/api/files/{bucket}/{filename}/export")
def export_file(
    bucket: str,
    filename: str,
    format: AudioExportFormat = "mp3",
    settings: Settings = Depends(get_settings),
):
    if bucket not in {"voices", "outputs", "uploads"}:
        raise HTTPException(status_code=404, detail="내려받을 파일을 찾지 못했습니다.")
    base = {"voices": settings.voices_dir, "outputs": settings.outputs_dir, "uploads": settings.uploads_dir}[bucket]
    try:
        path = (base / filename).resolve()
        if path.parent != base.resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="내려받을 파일을 찾지 못했습니다.")
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="내려받을 파일을 찾지 못했습니다.") from exc
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=422, detail="오디오 파일만 MP3 또는 WAV로 내려받을 수 있습니다.")
    try:
        return export_audio_file(path, format)
    except AudioExportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/files/{bucket}/{filename}")
def get_file(
    bucket: str,
    filename: str,
    download: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
):
    if bucket not in {"voices", "outputs", "uploads"}:
        raise HTTPException(status_code=404, detail="File bucket was not found")
    base = {"voices": settings.voices_dir, "outputs": settings.outputs_dir, "uploads": settings.uploads_dir}[bucket]
    path = (base / filename).resolve()
    if not path.is_file() or path.parent != base.resolve():
        raise HTTPException(status_code=404, detail="File was not found")
    disposition = "attachment" if download else "inline"
    return FileResponse(path, filename=path.name, content_disposition_type=disposition)
