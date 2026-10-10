"""Canonical staff bodies reject silently ignored properties before owner execution."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.staff_membership_routes import add_staff_membership_routes
from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffResult,
    StaffMembershipCommands,
)
from request_engine.platform.security.context import ActorContext

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["invite", "authority", "status"])
@pytest.mark.parametrize("extra", ["organization_id", "role", "typo"])
async def test_staff_command_unknown_properties_rejected_before_owner(
    action: str,
    extra: str,
) -> None:
    commands = MagicMock(spec=StaffMembershipCommands)
    commands.invite_native_staff = AsyncMock(
        return_value=InviteNativeStaffResult(uuid4(), uuid4(), uuid4())
    )
    commands.replace_staff_authority = AsyncMock(return_value=2)
    commands.transition_staff_membership = AsyncMock(return_value=2)

    async def actor(request: Request) -> ActorContext:
        return ActorContext(
            uuid4(),
            uuid4(),
            frozenset({"staff.invite", "staff.manage_authority", "staff.manage_membership"}),
        )

    app = FastAPI()
    add_global_error_handlers(app)
    router = APIRouter(prefix="/v1/staff")
    add_staff_membership_routes(router, commands=commands, authenticated_actor=actor)
    app.include_router(router)
    if action == "invite":
        method, path = "POST", "/v1/staff/members/native"
        body: dict[str, object] = {
            "identity_authority_id": str(uuid4()),
            "native_identity_id": str(uuid4()),
            "provenance_reference": "test",
        }
        owner = commands.invite_native_staff
    else:
        method, path = "PUT", f"/v1/staff/members/{uuid4()}/{action}"
        body = {"provenance_reference": "test"}
        if action == "authority":
            body.update(expected_authority_revision=1, desired_capabilities=[])
            owner = commands.replace_staff_authority
        else:
            body.update(expected_revision=1, target_status="suspended")
            owner = commands.transition_staff_membership
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        rejected = await client.request(
            method,
            path,
            json={**body, extra: "unexpected-sentinel"},
            headers={"Idempotency-Key": "same-request"},
        )
        owner.assert_not_awaited()
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "validation_failed"
        assert "unexpected-sentinel" not in rejected.text
        accepted = await client.request(
            method, path, json=body, headers={"Idempotency-Key": "same-request"}
        )
    assert accepted.status_code == (201 if action == "invite" else 200)
    owner.assert_awaited_once()
    command = owner.await_args.args[1]
    assert command.idempotency_key == "same-request"
