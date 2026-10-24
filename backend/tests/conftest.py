"""Keep regression tests independent of the host's Apple Intelligence model."""
import pytest

from app.services.apple_foundation_models_service import AppleFoundationModelsService


@pytest.fixture(autouse=True)
def isolate_native_apple_status(request, monkeypatch):
    # Bridge unit tests explicitly fake subprocesses. Other tests opt into ready
    # Apple responses themselves; ordinary API tests never compile or probe it.
    if request.module.__name__.split(".")[-1] == "test_apple_foundation_models_service":
        return
    monkeypatch.setattr(AppleFoundationModelsService, "status", lambda self, **kwargs: {
        "available": False,
        "message": "Native Apple runtime is isolated during regression tests.",
        "model_id": "apple-on-device",
        "reason_code": "model_not_ready",
    })
