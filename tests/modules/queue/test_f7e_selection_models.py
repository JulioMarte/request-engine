import pytest
from pydantic import ValidationError

from request_engine.modules.queue.api.same_day_selection_models import RecallHoldBody


def test_recall_hold_http_rejects_free_text_reason() -> None:
    with pytest.raises(ValidationError):
        RecallHoldBody.model_validate(
            {
                "expected_revision": 1,
                "kind": "until_customer_initiates",
                "release_at": None,
                "reason": "patient has chest pain",
            }
        )


def test_recall_hold_http_accepts_closed_operational_reason() -> None:
    body = RecallHoldBody.model_validate(
        {
            "expected_revision": 1,
            "kind": "until_customer_initiates",
            "release_at": None,
            "reason": "stepped_away",
        }
    )
    assert body.reason is not None and body.reason.value == "stepped_away"
