"""All bearer arms preserve opaque, non-cacheable authentication failures."""

import json
from collections.abc import Awaitable, Callable

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from request_engine.entrypoints.http.native_auth_errors import (
    native_authentication_error_handler,
    oidc_authentication_error_handler,
    workload_authentication_error_handler,
)
from request_engine.platform.security.native_auth import CredentialInvalid
from request_engine.platform.security.oidc_auth import OidcAuthenticationRequired
from request_engine.platform.security.workload_auth import WorkloadCredentialInvalid

pytestmark = [pytest.mark.contract, pytest.mark.security, pytest.mark.adversarial]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "error_type"),
    [
        (native_authentication_error_handler, CredentialInvalid),
        (oidc_authentication_error_handler, OidcAuthenticationRequired),
        (workload_authentication_error_handler, WorkloadCredentialInvalid),
    ],
)
async def test_bearer_failure_is_opaque_and_not_cacheable(
    handler: Callable[[Request, Exception], Awaitable[JSONResponse]],
    error_type: type[Exception],
) -> None:
    private_detail = "private-provider-detail-and-submitted-secret"
    response = await handler(Request({"type": "http"}), error_type(private_detail))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = bytes(response.body)
    assert private_detail.encode() not in body
    assert json.loads(body)["error"]["code"] == "credential_invalid"
