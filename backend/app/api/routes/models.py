from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_router
from app.config import Settings, get_settings
from app.schemas import ModelListResponse, ModelPreferencesResponse, ModelPreferencesUpdateRequest
from app.services.model_preferences import get_model_preferences, save_model_preferences
from app.services.model_router import ModelRouter, ModelUnavailableError

router = APIRouter()

@router.get("/api/models", response_model=ModelListResponse)
def list_runtime_models(settings: Settings = Depends(get_settings), router: ModelRouter = Depends(get_router)):
    models = router.list()
    preferences = get_model_preferences(settings, models, persist_default=True)
    return ModelListResponse(
        models=models,
        default_tts_model=preferences.default_tts_model,
        default_vc_model=preferences.default_vc_model,
        model_preferences=preferences.model_preferences,
    )


@router.put("/api/models/preferences", response_model=ModelPreferencesResponse)
def update_model_preferences(
    request: ModelPreferencesUpdateRequest,
    settings: Settings = Depends(get_settings),
    router: ModelRouter = Depends(get_router),
):
    return save_model_preferences(settings, router.list(), request)


@router.post("/api/models/{model_id}/preload")
def preload_runtime_model(model_id: str, router: ModelRouter = Depends(get_router)):
    try:
        return router.preload(model_id)
    except ModelUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
