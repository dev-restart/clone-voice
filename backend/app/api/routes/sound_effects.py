from __future__ import annotations

import asyncio
from secrets import randbelow
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_router
from app.config import Settings, get_settings
from app.i18n import tr
from app.schemas import (
    SoundEffectGenerateRequest,
    SoundEffectGenerateResponse,
    SoundEffectPromptPlan,
    SoundEffectResult,
    public_file_url,
)
from app.services.model_helpers import ensure_adapter_available
from app.services.model_router import CapabilityUnsupportedError, ModelRouter, ModelUnavailableError
from app.services.progress import publish_progress
from app.services.sound_effect_prompt_service import plan_sound_effect_prompt
from app.services.sound_project_store import SoundProjectError, SoundProjectStore

router = APIRouter()


@router.post("/api/sound-effects/generate", response_model=SoundEffectGenerateResponse)
async def generate_sound_effects(
    request: SoundEffectGenerateRequest,
    settings: Settings = Depends(get_settings),
    router: ModelRouter = Depends(get_router),
):
    project_store = SoundProjectStore(settings)
    if request.project_id and request.asset_id:
        try:
            project = project_store.get(request.project_id)
        except SoundProjectError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if not any(asset.id == request.asset_id for asset in project.assets):
            raise HTTPException(status_code=404, detail=tr("사운드가 삭제되었거나 프로젝트에 없습니다.", "The sound was deleted or is not in the project."))
    results: list[SoundEffectResult] = []
    generation_warning = None
    publish_progress(request.progress_id, 4, tr("효과음 모델을 확인하고 있습니다.", "Checking the sound-effect model…"))
    try:
        adapter = ensure_adapter_available(router, request.model_id or settings.default_sfx_model, "sound_effect_generation")
        if not adapter.status().capabilities.sound_effect_generation:
            raise CapabilityUnsupportedError(f"{adapter.label} does not support sound-effect generation.")

        publish_progress(request.progress_id, 7, tr("설명을 생성용 Prompt로 정리하고 길이를 판단하고 있습니다.", "Turning the description into a generation prompt and choosing the length…"))
        plan = await asyncio.to_thread(
            plan_sound_effect_prompt,
            request.prompt,
            settings,
            auto_duration=request.auto_duration,
            requested_duration=request.duration_seconds,
        )
        base_seed = request.seed if request.seed is not None else randbelow(2_147_483_647 - request.variations)
        for index in range(request.variations):
            seed = base_seed + index
            publish_progress(
                request.progress_id,
                10 + int((index / request.variations) * 78),
                tr(f"효과음 시안 {index + 1}/{request.variations}을 생성하고 있습니다.", f"Generating sound-effect variation {index + 1}/{request.variations}…"),
            )
            output = await asyncio.to_thread(
                adapter.generate_sound_effect,
                prompt=plan.generation_prompt,
                negative_prompt=request.negative_prompt,
                duration_seconds=plan.duration_seconds,
                steps=request.steps,
                guidance_scale=request.guidance_scale,
                seed=seed,
            )
            results.append(
                SoundEffectResult(
                    id=uuid4().hex,
                    prompt=request.prompt,
                    generation_prompt=plan.generation_prompt,
                    negative_prompt=request.negative_prompt,
                    audio_url=public_file_url(output.path, "outputs"),
                    duration_seconds=output.duration_seconds or plan.duration_seconds,
                    seed=seed,
                )
            )
    except (CapabilityUnsupportedError, ModelUnavailableError) as exc:
        if not results:
            publish_progress(request.progress_id, 100, str(exc), done=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        generation_warning = tr(f"{request.variations}개 중 {len(results)}개를 생성했습니다. 나머지 생성 실패: {exc}", f"Generated {len(results)} of {request.variations}. The rest failed: {exc}")
    except Exception as exc:
        if not results:
            publish_progress(request.progress_id, 100, tr(f"효과음 생성 실패: {exc}", f"Sound-effect generation failed: {exc}"), done=True)
            raise HTTPException(status_code=503, detail=f"Sound-effect generation failed: {exc}") from exc
        generation_warning = tr(f"{request.variations}개 중 {len(results)}개를 생성했습니다. 나머지 생성 실패: {exc}", f"Generated {len(results)} of {request.variations}. The rest failed: {exc}")

    stored_project = None
    storage_warning = None
    if request.project_id and request.asset_id:
        try:
            stored_project = project_store.save_result(request.project_id, request.asset_id, results)
        except Exception as exc:
            # Audio is already generated. Preserve it in the response and output
            # library if the target was removed or the metadata save conflicted.
            storage_warning = tr(f"오디오는 생성했지만 프로젝트에 연결하지 못했습니다. {exc}", f"The audio was generated but could not be linked to the project. {exc}")
    publish_progress(request.progress_id, 100, storage_warning or generation_warning or tr("효과음 생성이 완료되었습니다.", "Sound-effect generation is complete."), done=True)
    return SoundEffectGenerateResponse(
        results=results, plan=SoundEffectPromptPlan(**plan.__dict__),
        project=stored_project.model_dump(mode="json") if stored_project else None,
        storage_warning=storage_warning, generation_warning=generation_warning,
    )
