from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_voice_store
from app.schemas import GenerationPreviewRequest, GenerationPreviewResponse
from app.services.generation_helpers import build_generation_preview
from app.services.voice_store import VoiceStore

router = APIRouter()

@router.post("/api/generation/preview", response_model=GenerationPreviewResponse)
def preview_generation_options(request: GenerationPreviewRequest, store: VoiceStore = Depends(get_voice_store)):
    voice = store.get(request.voice_id) if request.voice_id else None
    if request.voice_id and voice is None:
        raise HTTPException(status_code=404, detail="Voice profile was not found")
    return build_generation_preview(request, voice)
