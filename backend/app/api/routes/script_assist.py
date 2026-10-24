from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.schemas import ScriptAssistRequest, ScriptAssistResponse
from app.services.script_assist_service import assist_script

router = APIRouter()


@router.post("/api/tts/script-assist", response_model=ScriptAssistResponse)
def create_script_assist(request: ScriptAssistRequest, settings: Settings = Depends(get_settings)):
    try:
        return assist_script(request, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"AI 대본 도우미를 사용할 수 없습니다: {exc}") from exc
