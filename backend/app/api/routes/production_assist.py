from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.routes.ai_profiles import local_ui
from app.config import Settings, get_settings
from app.services.production_assist_service import (
    ProductionAssistRequest,
    ProductionAssistResponse,
    ProductionOutputError,
    assist_production,
)
from app.services.production_prompt_store import ProductionPromptStore, PromptConflict, PromptUpdateRequest


class ProductionValidationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def safe(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # Never echo private briefs, custom prompts or arbitrary request values.
                return JSONResponse(status_code=422, content={
                    "detail": "제작 보조 입력이 올바르지 않습니다. 설명·프롬프트 길이와 현재 커버 설정을 확인하세요."
                })
        return safe


router = APIRouter(route_class=ProductionValidationRoute, dependencies=[Depends(local_ui)])


@router.get("/api/ai/production/prompts")
def get_production_prompts(settings: Settings = Depends(get_settings)):
    try:
        return ProductionPromptStore(settings).public()
    except (RuntimeError, OSError):
        raise HTTPException(503, "제작 프롬프트 설정을 읽지 못했습니다. 기존 파일은 변경하지 않았습니다.") from None


@router.put("/api/ai/production/prompts")
def update_production_prompts(request: PromptUpdateRequest, settings: Settings = Depends(get_settings)):
    try:
        return ProductionPromptStore(settings).update(request)
    except PromptConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (RuntimeError, OSError):
        raise HTTPException(503, "제작 프롬프트를 저장하지 못했습니다. 입력을 유지한 채 다시 시도하세요.") from None


@router.post("/api/ai/production/assist", response_model=ProductionAssistResponse)
def production_assist(request: ProductionAssistRequest, settings: Settings = Depends(get_settings)):
    try:
        return assist_production(request, settings)
    except ProductionOutputError as exc:
        raise HTTPException(503, str(exc)) from None
    except (RuntimeError, ValueError, OSError):
        # Provider response bodies and custom prompt content are not public errors.
        raise HTTPException(503, "제작 보조 응답을 확인하지 못했습니다. AI 연결·모델과 요청을 확인하세요.") from None
