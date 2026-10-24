import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_router
from app.api.routes.ai_profiles import SafeValidationRoute, local_ui
from app.config import Settings, get_settings
from app.schemas import (
    AiTextConnectionUpdateRequest,
    AiTextSelectionRequest,
    SmokeTestRequest,
    SmokeTestResponse,
    TranslateRequest,
    TranslateResponse,
    public_file_url,
)
from app.services.ai_text_provider_service import AiTextProviderService, get_provider_login, start_provider_login
from app.services.generation_helpers import (
    ensure_generated_audio,
)
from app.services.model_router import ModelRouter
from app.services.omnivoice_service import (
    MockVoiceEngine,
    OmniVoiceEngine,
    get_voice_engine,
)
from app.services.translation_service import OpenAICompatibleTranslator

# The compatibility settings endpoint may also receive API keys.
router = APIRouter(route_class=SafeValidationRoute, dependencies=[Depends(local_ui)])


@router.get("/api/ai/providers")
def get_ai_providers(settings: Settings = Depends(get_settings)):
    return AiTextProviderService(settings).catalog()


@router.put("/api/ai/providers/selection")
def update_ai_provider_selection(request: AiTextSelectionRequest, settings: Settings = Depends(get_settings)):
    service = AiTextProviderService(settings)
    try:
        service.save_selection(request.provider_id, request.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return service.catalog()


@router.put("/api/ai/providers/connections")
def update_ai_connections(request: AiTextConnectionUpdateRequest, settings: Settings = Depends(get_settings)):
    try:
        return AiTextProviderService(settings).update_connection(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/ai/providers/test")
def test_ai_connection(request: AiTextSelectionRequest, settings: Settings = Depends(get_settings)):
    try:
        result = AiTextProviderService(settings).complete(
            "Reply with OK only.", system_prompt="This is a connection check.",
            provider_id=request.provider_id, model_id=request.model_id, max_tokens=32,
        )
        if result.content.strip().strip('"\'').rstrip(".!").upper() != "OK":
            raise RuntimeError("연결은 됐지만 모델이 확인 요청대로 응답하지 않았습니다. 번역 확인으로 결과를 점검하세요.")
        return {"ok": True, "provider": result.provider, "model": result.model}
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc



@router.post("/api/ai/translation/test")
def test_translation_engine(settings: Settings = Depends(get_settings)):
    # A fixed public sample makes the engine and prompt test reviewable without using private scripts.
    sample = "안녕하세요. 크론보이스는 내 목소리로 안내 음성을 만듭니다. 오늘 오후 3시에 회의를 시작합니다."
    started = time.monotonic()
    try:
        result = OpenAICompatibleTranslator(settings).translate(sample, ["en"])
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True, "provider": result.provider, "model": result.model,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "source_text": sample, "translations": result.translations,
        "detail": "선택한 번역 엔진의 실제 번역 결과입니다. 원문과 숫자·의미를 비교해 주세요.",
    }

@router.post("/api/ai/providers/{provider_id}/login")
def login_ai_provider(provider_id: str, settings: Settings = Depends(get_settings)):
    if AiTextProviderService(settings).connections.get()["local_only"]:
        raise HTTPException(status_code=409, detail="외부 계정 연결은 로컬 전용을 해제한 뒤 사용할 수 있습니다.")
    try:
        return start_provider_login(settings, provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/ai/providers/login/{session_id}")
def get_ai_provider_login(session_id: str):
    try:
        return get_provider_login(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/api/translate", response_model=TranslateResponse)
def translate_text(request: TranslateRequest, settings: Settings = Depends(get_settings)):
    try:
        result = OpenAICompatibleTranslator(settings).translate(request.text, request.languages)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Translation failed: {exc}") from exc
    return TranslateResponse(source_text=request.text, translations=result.translations, provider=result.provider, model=result.model)


@router.get("/api/settings")
def get_runtime_settings(settings: Settings = Depends(get_settings), engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine), router: ModelRouter = Depends(get_router)):
    return {
        "voice_model": engine.status().model_dump(mode="json"),
        "models": [model.model_dump(mode="json") for model in router.list()],
        "default_tts_model": settings.default_tts_model,
        "default_vc_model": settings.default_vc_model,
        "translation": {"base_url": settings.llm_base_url, "model": settings.llm_model,
                        **AiTextProviderService(settings).translation_status()},
    }


@router.post("/api/settings/test-voice", response_model=SmokeTestResponse)
def test_voice_settings(
    request: SmokeTestRequest,
    engine: MockVoiceEngine | OmniVoiceEngine = Depends(get_voice_engine),
):
    try:
        output_path, duration = engine.generate(text=request.text, speed=1.0, num_step=16)
        ensure_generated_audio(output_path, duration)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Voice test failed: {exc}") from exc
    return SmokeTestResponse(ok=True, detail="Voice test succeeded.", audio_url=public_file_url(output_path, "outputs"))


@router.post("/api/settings/test-translation", response_model=SmokeTestResponse)
def test_translation_settings(request: SmokeTestRequest, settings: Settings = Depends(get_settings)):
    try:
        result = OpenAICompatibleTranslator(settings).translate(request.text, request.languages)
        return SmokeTestResponse(ok=True, detail="Translation test succeeded.", translations=result.translations)
    except Exception as exc:
        return SmokeTestResponse(ok=False, detail=f"Translation test failed: {exc}", translations={})
