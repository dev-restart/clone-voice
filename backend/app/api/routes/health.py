from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_router
from app.config import Settings, get_settings
from app.schemas import HealthResponse, ModelStatus, RuntimeModelStatus
from app.services.model_router import ModelRouter

router = APIRouter()


def health_model_status(status: RuntimeModelStatus) -> ModelStatus:
    return ModelStatus(
        engine=status.id,
        loaded=status.loaded,
        model_id=status.model_id,
        device=status.device,
        error=None if status.status == "available" else status.message,
    )


@router.get("/api/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings), model_router: ModelRouter = Depends(get_router)):
    models = model_router.list()
    selected = next((model for model in models if model.id == settings.default_tts_model), None)
    selected = selected or next((model for model in models if model.capabilities.tts), None)
    if selected is None:
        return HealthResponse(
            ok=True,
            model=ModelStatus(engine="unconfigured", loaded=False, error="등록된 TTS 모델이 없습니다."),
        )
    return HealthResponse(ok=True, model=health_model_status(selected))


@router.post("/api/model/preload", response_model=ModelStatus)
def preload_model(settings: Settings = Depends(get_settings), model_router: ModelRouter = Depends(get_router)):
    status = model_router.preload(settings.default_tts_model)
    if status.status != "available":
        raise HTTPException(status_code=503, detail=status.message or f"{status.label} 모델을 불러오지 못했습니다.")
    return health_model_status(status)
