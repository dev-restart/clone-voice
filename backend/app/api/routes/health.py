from fastapi import APIRouter, Depends, HTTPException

from app.schemas import HealthResponse
from app.services.omnivoice_service import MockVoiceEngine, OmniVoiceEngine, get_voice_engine

router = APIRouter()

@router.get("/api/health", response_model=HealthResponse)
def health(engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine)):
    return HealthResponse(ok=True, model=engine.status())


@router.post("/api/model/preload")
def preload_model(engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine)):
    try:
        return engine.preload()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OmniVoice model could not be loaded: {exc}") from exc
