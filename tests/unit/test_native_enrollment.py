"""Native enrollment transport: no client-supplied authority or secret reflection."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from request_engine.entrypoints.http.errors import request_validation_error_handler
from request_engine.entrypoints.http.native_auth import (
    NativeLoginRequest,
    NativePasswordRotationRequest,
    create_native_auth_router,
)
from request_engine.platform.security.native_auth import PasswordPolicyViolation
from request_engine.platform.security.native_human_auth import (
    NativeHumanAuthService,
    NativeIdentityAlreadyExists,
    NativeIdentityEnrollment,
)
from request_engine.platform.security.native_session import NativeSessionAuthenticator

pytestmark = [pytest.mark.unit, pytest.mark.security]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["created", "duplicate", "password", "authority", "blank"])
async def test_native_enrollment_transport(scenario: str) -> None:
    authority_id, identity_id = uuid4(), uuid4()
    enroll = AsyncMock(
        return_value=NativeIdentityEnrollment(identity_id, uuid4(), "reception@example.test")
    )
    service = Mock(spec=NativeHumanAuthService)
    service.enroll_password_identity = enroll
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.include_router(
        create_native_auth_router(
            service=service,
            authenticator=Mock(spec=NativeSessionAuthenticator),
            identity_authority_id=authority_id,
        )
    )
    password = "secret enrollment password"
    body = {"login_handle": " Reception@Example.Test ", "password": password}
    expected_status = 201
    if scenario == "duplicate":
        enroll.side_effect = NativeIdentityAlreadyExists(password)
        expected_status = 409
    elif scenario == "password":
        enroll.side_effect = PasswordPolicyViolation(password)
        expected_status = 422
    elif scenario == "authority":
        body["identity_authority_id"] = str(uuid4())
        body["principal_id"] = str(uuid4())
        expected_status = 422
    elif scenario == "blank":
        body["login_handle"] = "   "
        expected_status = 422
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/native/identities", json=body)
    assert response.status_code == expected_status, response.text
    assert password not in response.text
    if scenario in {"authority", "blank"}:
        enroll.assert_not_awaited()
        assert response.json()["error"]["code"] == "validation_failed"
    else:
        enroll.assert_awaited_once_with(
            identity_authority_id=authority_id,
            login_handle="reception@example.test",
            password=password,
        )
        assert response.headers["cache-control"] == "no-store"
        if scenario == "created":
            assert response.json() == {
                "native_identity_id": str(identity_id),
                "identity_authority_id": str(authority_id),
                "login_handle": "reception@example.test",
            }
        else:
            expected_code = (
                "native_identity_already_exists"
                if scenario == "duplicate"
                else "password_policy_violation"
            )
            assert response.json()["error"]["code"] == expected_code
    service.authenticate_password.assert_not_called()


@pytest.mark.parametrize("rotation", [False, True])
@pytest.mark.parametrize("invalid_input", ["blank_handle", "injected_authority"])
def test_native_credential_inputs_reject_ambiguous_identity_fields(
    rotation: bool, invalid_input: str
) -> None:
    body = {"login_handle": " User@Example.Test "}
    if rotation:
        body.update(current_password="current password", new_password="new secure password")
        model = NativePasswordRotationRequest
    else:
        body["password"] = "current password"
        model = NativeLoginRequest
    valid = model.model_validate(body)
    assert valid.login_handle == "user@example.test"
    if invalid_input == "blank_handle":
        body["login_handle"] = "   "
    else:
        body["identity_authority_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        model.model_validate(body)
