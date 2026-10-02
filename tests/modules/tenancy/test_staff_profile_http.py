from typing import cast
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.modules.tenancy.api.staff_membership_routes import add_staff_membership_routes
from request_engine.modules.tenancy.application.commands.staff_membership import (
    StaffMembershipCommands,
    UpdateStaffProfileCommand,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class RecordingProfileCommands:
    def __init__(self) -> None:
        self.calls: list[UpdateStaffProfileCommand] = []

    async def update_staff_profile(
        self, actor: ActorContext, command: UpdateStaffProfileCommand
    ) -> int:
        del actor
        self.calls.append(command)
        return command.expected_profile_revision + 1


def _app(*, allowed: bool = True, human: bool = True) -> tuple[FastAPI, RecordingProfileCommands]:
    commands = RecordingProfileCommands()
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"staff.manage_membership"}) if allowed else frozenset(),
        principal_kind=PrincipalKind.HUMAN if human else PrincipalKind.AGENT,
    )

    async def authenticated_actor(request: Request) -> ActorContext:
        del request
        return actor

    router = APIRouter(prefix="/v1/staff")
    add_staff_membership_routes(
        router,
        commands=cast(StaffMembershipCommands, commands),
        authenticated_actor=authenticated_actor,
    )
    app = FastAPI()
    app.include_router(router)
    add_staff_membership_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return app, commands


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["María Chen", None])
async def test_profile_patch_is_canonical_typed_command_with_independent_revision(
    name: str | None,
) -> None:
    app, commands = _app()
    member = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.patch(
            f"/v1/staff/members/{member}/profile",
            headers={"Idempotency-Key": "profile:test"},
            json={
                "display_name": name,
                "expected_profile_revision": 0,
                "provenance_reference": "test",
            },
        )
    assert response.status_code == 200
    assert response.json() == {"profile_revision": 1}
    assert commands.calls == [UpdateStaffProfileCommand(member, name, 0, "test", "profile:test")]
    operation = app.openapi()["paths"]["/v1/staff/members/{membership_id}/profile"]["patch"]
    assert operation["operationId"] == "staff_profile_update"
    assert operation["x-request-engine-owner"] == "tenancy"
    assert operation["x-request-engine-capability"] == "staff.manage_membership"
    assert operation["x-request-engine-idempotency"] == "required"


@pytest.mark.asyncio
@pytest.mark.parametrize(("allowed", "human"), [(False, True), (True, False)])
async def test_profile_patch_cannot_infer_authority_from_target(allowed: bool, human: bool) -> None:
    app, commands = _app(allowed=allowed, human=human)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.patch(
            f"/v1/staff/members/{uuid4()}/profile",
            headers={"Idempotency-Key": "test"},
            json={
                "display_name": "Name",
                "expected_profile_revision": 0,
                "provenance_reference": "test",
            },
        )
    assert response.status_code == 403
    assert commands.calls == []


@pytest.mark.asyncio
async def test_profile_patch_requires_key_and_rejects_authority_fields() -> None:
    app, commands = _app()
    body = {"display_name": None, "expected_profile_revision": 0, "provenance_reference": "test"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        no_key = await http.patch(f"/v1/staff/members/{uuid4()}/profile", json=body)
        forged = await http.patch(
            f"/v1/staff/members/{uuid4()}/profile",
            headers={"Idempotency-Key": "test"},
            json={**body, "organization_id": str(uuid4()), "authority_revision": 12},
        )
    assert no_key.status_code == 422
    assert forged.status_code == 422
    assert commands.calls == []
