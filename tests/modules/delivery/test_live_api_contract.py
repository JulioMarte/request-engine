import pytest
from pydantic import ValidationError

from request_engine.modules.delivery.api.live_models import (
    PauseServiceBody,
    StartResourceActivityBody,
)
from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ResourceActivityKind,
)


def test_pause_body_validates_interruption_kind_at_boundary() -> None:
    body = PauseServiceBody.model_validate({"expected_revision": 1, "kind": "break"})
    assert body.kind is InterruptionKind.BREAK
    with pytest.raises(ValidationError):
        PauseServiceBody.model_validate({"expected_revision": 1, "kind": "clinical_note"})


def test_resource_activity_body_validates_kind_at_boundary() -> None:
    payload = {
        "resource_id": "00000000-0000-4000-8000-000000000001",
        "kind": "emergency",
    }
    body = StartResourceActivityBody.model_validate(payload)
    assert body.kind is ResourceActivityKind.EMERGENCY
    with pytest.raises(ValidationError):
        StartResourceActivityBody.model_validate(
            {
                "resource_id": "00000000-0000-4000-8000-000000000001",
                "kind": "patient_service",
            }
        )
