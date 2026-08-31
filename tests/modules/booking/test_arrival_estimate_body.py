from typing import Any

import pytest
from pydantic import ValidationError

from request_engine.modules.booking.api.models import ArrivalEstimateBody


def _payload(estimated_arrival_at: str) -> dict[str, Any]:
    return {
        "estimated_arrival_at": estimated_arrival_at,
        "source_kind": "customer",
        "expected_revision": 1,
    }


def test_naive_arrival_timestamp_fails_request_validation() -> None:
    """A timezone-naive instant must fail body validation (HTTP 422 validation_failed),
    never reach the application command as an ambiguous wall-clock value."""

    with pytest.raises(ValidationError) as error:
        ArrivalEstimateBody.model_validate(_payload("2026-08-31T10:15:00"))

    field_errors = [
        item for item in error.value.errors() if item["loc"] == ("estimated_arrival_at",)
    ]
    assert field_errors
    assert "UTC offset" in str(field_errors[0]["msg"])


def test_aware_arrival_timestamp_is_accepted() -> None:
    body = ArrivalEstimateBody.model_validate(_payload("2026-08-31T10:15:00-04:00"))

    assert body.estimated_arrival_at.utcoffset() is not None
    assert body.source_kind == "customer"
    assert body.expected_revision == 1
