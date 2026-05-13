from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings, get_settings

router = APIRouter()

@router.get("/api/files/{bucket}/{filename}")
def get_file(bucket: str, filename: str, settings: Settings = Depends(get_settings)):
    if bucket not in {"voices", "outputs", "uploads"}:
        raise HTTPException(status_code=404, detail="File bucket was not found")
    base = {"voices": settings.voices_dir, "outputs": settings.outputs_dir, "uploads": settings.uploads_dir}[bucket]
    path = (base / filename).resolve()
    if not path.exists() or path.parent != base.resolve():
        raise HTTPException(status_code=404, detail="File was not found")
    return FileResponse(path)
