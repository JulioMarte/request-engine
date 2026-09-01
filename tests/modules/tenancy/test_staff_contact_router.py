"""Staff contact route behavior (DB-free).

Bodies map into the application commands with `principal_id` forced from the
actor; integration callers get the typed 403; capability grants are
enforced; typed verification errors map to their HTTP statuses. The
issued-verification view never carries a code.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _staff_contact_route_support import actor, app, client, contact

from request_engine.modules.tenancy.application.errors import (
    PrincipalContactNotFound,
    VerificationAttemptsExhausted,
    VerificationCodeExpired,
    VerificationCodeInvalid,
)
from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContactVerificationIssued,
)
from request_engine.platform.security.context import PrincipalKind

_GRANT = "staff.manage_own_admin_contact"
_CONFIRM_GRANT = "staff.confirm_own_admin_contact"


@pytest.mark.asyncio
async def test_register_maps_body_and_forces_principal_from_actor() -> None:
    test_actor = actor(_GRANT)
    test_app, commands = app(test_actor, contact())
    async with client(test_app) as http:
        response = await http.post(
            "/v1/staff/contacts",
            json={"channel": "whatsapp", "value": "(809) 555-1234"},
            headers={"Idempotency-Key": "register-staff"},
        )
    assert response.status_code == 201, response.text
    command = commands.register_commands[0]
    assert command.principal_id == test_actor.principal_id
    assert command.organization_id == test_actor.organization_id
    assert command.value == "+18095551234"
    assert response.json()["verified"] is False


@pytest.mark.asyncio
async def test_integration_actor_gets_typed_403_without_reaching_handler() -> None:
    test_actor = actor(_GRANT, _CONFIRM_GRANT, kind=PrincipalKind.INTEGRATION)
    test_app, commands = app(test_actor, contact())
    async with client(test_app) as http:
        response = await http.post(
            "/v1/staff/contacts",
            json={"channel": "whatsapp", "value": "+18095551234"},
            headers={"Idempotency-Key": "register-integration"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "staff_contact_forbidden"
    assert commands.register_commands == []


@pytest.mark.asyncio
async def test_missing_capability_grant_is_403_without_reaching_handler() -> None:
    test_app, commands = app(actor(), contact())
    async with client(test_app) as http:
        response = await http.post(
            f"/v1/staff/contacts/{uuid4()}/confirm",
            json={"code": "123456"},
            headers={"Idempotency-Key": "confirm-no-grant"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "capability_required"
    assert commands.confirm_commands == []


@pytest.mark.asyncio
async def test_request_verification_view_never_carries_a_code() -> None:
    registered = contact()
    test_actor = actor(_GRANT)
    issued = PrincipalContactVerificationIssued(
        contact_id=registered.contact_id, expires_at=datetime.now(UTC) + timedelta(minutes=15)
    )
    test_app, commands = app(test_actor, issued)
    async with client(test_app) as http:
        response = await http.post(
            f"/v1/staff/contacts/{registered.contact_id}/request-verification",
            headers={"Idempotency-Key": "request-verification"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"contact_id", "expires_at"}
    assert body["contact_id"] == str(registered.contact_id)
    command = commands.request_commands[0]
    assert command.principal_id == test_actor.principal_id
    assert command.contact_id == registered.contact_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "status_code", "code"),
    (
        (VerificationCodeInvalid(2), 422, "verification_code_invalid"),
        (VerificationCodeExpired(), 410, "verification_code_expired"),
        (VerificationAttemptsExhausted(), 429, "verification_attempts_exhausted"),
        (PrincipalContactNotFound(uuid4(), uuid4()), 404, "principal_contact_not_found"),
    ),
)
async def test_typed_error_mappings(outcome: Exception, status_code: int, code: str) -> None:
    test_app, _commands = app(actor(_GRANT, _CONFIRM_GRANT), outcome)
    async with client(test_app) as http:
        response = await http.post(
            f"/v1/staff/contacts/{uuid4()}/confirm",
            json={"code": "123456"},
            headers={"Idempotency-Key": "confirm-error"},
        )
    assert response.status_code == status_code, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.asyncio
async def test_invalid_code_error_carries_attempts_remaining() -> None:
    test_app, _commands = app(actor(_GRANT, _CONFIRM_GRANT), VerificationCodeInvalid(2))
    async with client(test_app) as http:
        response = await http.post(
            f"/v1/staff/contacts/{uuid4()}/confirm",
            json={"code": "123456"},
            headers={"Idempotency-Key": "confirm-invalid"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["attempts_remaining"] == 2
