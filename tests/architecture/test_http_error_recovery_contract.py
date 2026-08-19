import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from request_engine.entrypoints.http.errors import (
    http_exception_handler,
    request_validation_error_handler,
)
from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.application.errors import (
    SubjectAuthorityRequired as BookingAuthorityRequired,
)
from request_engine.modules.queue.api.errors import queue_error_handler
from request_engine.modules.queue.application.errors import (
    SubjectAuthorityRequired as QueueAuthorityRequired,
)
from request_engine.modules.requests.api.errors import request_error_handler
from request_engine.modules.requests.application.errors import RequestPartyAuthorityRequired


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


@pytest.mark.asyncio
async def test_fastapi_validation_uses_error_envelope_and_fix_request_resolution() -> None:
    response = await request_validation_error_handler(
        _request(),
        RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body", "expected_revision"),
                    "msg": "Field required",
                    "input": {},
                }
            ]
        ),
    )

    assert response.status_code == 422
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": "validation_failed",
            "message": "the request did not satisfy the operation input contract",
            "retryable": False,
            "resolution": "fix_request",
            "details": {
                "fields": [
                    {
                        "location": ["body", "expected_revision"],
                        "message": "Field required",
                        "type": "missing",
                    }
                ]
            },
        }
    }


@pytest.mark.asyncio
async def test_residual_http_exception_cannot_escape_common_envelope() -> None:
    response = await http_exception_handler(
        _request(),
        HTTPException(status_code=404, detail="Offering not found"),
    )
    assert response.status_code == 404
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": "not_found",
            "message": "Offering not found",
            "retryable": False,
            "resolution": "fix_request",
            "details": {"status_code": 404},
        }
    }


@pytest.mark.asyncio
async def test_party_authority_errors_share_one_public_code_and_resolution() -> None:
    party_id = uuid4()
    responses = (
        await booking_error_handler(
            _request(),
            BookingAuthorityRequired(party_id, "appointments.manage"),
        ),
        await queue_error_handler(
            _request(),
            QueueAuthorityRequired(party_id, "queue.manage"),
        ),
        await request_error_handler(
            _request(),
            RequestPartyAuthorityRequired(party_id, "requests.manage"),
        ),
    )

    bodies = [json.loads(bytes(response.body))["error"] for response in responses]
    assert all(response.status_code == 403 for response in responses)
    assert {body["code"] for body in bodies} == {"party_authority_required"}
    assert {body["resolution"] for body in bodies} == {"request_authority"}
    assert [body["details"]["authority_anchor"] for body in bodies] == [
        "subject",
        "subject",
        "requester",
    ]
