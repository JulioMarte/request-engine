import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from request_engine.modules.requests.api.errors import request_error_handler
from request_engine.modules.requests.api.models import (
    CancelRequestBody,
    CompleteRequestBody,
    FailRequestBody,
    RecordRequestResultBody,
)
from request_engine.modules.requests.application.errors import RequestRevisionConflict


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_request_mutation_bodies_require_expected_revision() -> None:
    with pytest.raises(ValidationError):
        RecordRequestResultBody.model_validate({"result_payload": {}})
    with pytest.raises(ValidationError):
        CompleteRequestBody.model_validate({})
    with pytest.raises(ValidationError):
        CancelRequestBody.model_validate({})
    with pytest.raises(ValidationError):
        FailRequestBody.model_validate({"error_class": "provider_error"})


def test_request_mutation_bodies_reject_non_positive_revision() -> None:
    with pytest.raises(ValidationError):
        RecordRequestResultBody.model_validate({"result_payload": {}, "expected_revision": 0})
    with pytest.raises(ValidationError):
        CompleteRequestBody.model_validate({"expected_revision": 0})
    with pytest.raises(ValidationError):
        CancelRequestBody.model_validate({"expected_revision": 0})
    with pytest.raises(ValidationError):
        FailRequestBody.model_validate(
            {"error_class": "provider_error", "expected_revision": 0}
        )


@pytest.mark.asyncio
async def test_request_revision_conflict_uses_common_machine_readable_shape() -> None:
    request_id = uuid4()
    response = await request_error_handler(
        _request(),
        RequestRevisionConflict(request_id, 4, 5),
    )

    assert response.status_code == 409
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": "revision_conflict",
            "message": "the aggregate changed since it was read",
            "retryable": False,
            "details": {
                "aggregate_kind": "Request",
                "aggregate_id": str(request_id),
                "expected_revision": 4,
                "current_revision": 5,
            },
        }
    }
