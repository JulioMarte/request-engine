from uuid import uuid4

from pydantic import ValidationError

from request_engine.modules.requests.api.errors import _request_error
from request_engine.modules.requests.api.models import (
    CancelRequestBody,
    CompleteRequestBody,
    FailRequestBody,
    RecordRequestResultBody,
)
from request_engine.modules.requests.application.errors import RequestRevisionConflict


def test_request_mutation_bodies_require_expected_revision() -> None:
    invalid_payloads = (
        (RecordRequestResultBody, {"result_payload": {}}),
        (CompleteRequestBody, {}),
        (CancelRequestBody, {}),
        (FailRequestBody, {"error_class": "provider_error"}),
    )
    for model, payload in invalid_payloads:
        try:
            model.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"{model.__name__} must require expected_revision")


def test_request_mutation_bodies_reject_non_positive_revision() -> None:
    invalid_payloads = (
        (RecordRequestResultBody, {"result_payload": {}, "expected_revision": 0}),
        (CompleteRequestBody, {"expected_revision": 0}),
        (CancelRequestBody, {"expected_revision": 0}),
        (
            FailRequestBody,
            {"error_class": "provider_error", "expected_revision": 0},
        ),
    )
    for model, payload in invalid_payloads:
        try:
            model.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"{model.__name__} must reject non-positive expected_revision")


def test_request_revision_conflict_uses_common_machine_readable_shape() -> None:
    request_id = uuid4()
    status_code, body = _request_error(RequestRevisionConflict(request_id, 4, 5))

    assert status_code == 409
    assert body.code == "revision_conflict"
    assert body.retryable is False
    assert body.details == {
        "aggregate_kind": "Request",
        "aggregate_id": str(request_id),
        "expected_revision": 4,
        "current_revision": 5,
    }
