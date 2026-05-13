from app.services.model_router import ModelRouter, ModelUnavailableError


def ensure_adapter_available(router: ModelRouter, model_id: str | None, purpose: str):
    adapter = router.get(model_id, purpose=purpose)
    status = adapter.status()
    if status.status == "unavailable":
        raise ModelUnavailableError(status.message or f"{status.label} is unavailable")
    return adapter
