"""Canonical invitation acceptance preserves the subject/tenant boundary."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.staff_invitations import create_staff_invitation_router
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    ChangeStaffInvitationCommand,
    CreateStaffInvitationCommand,
    StaffInvitation,
)
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _Resolver:
    def __init__(self) -> None:
        self.verified = AuthenticatedHttpSubject(
            AuthenticatedSubject(str(uuid4()), str(uuid4()), AuthenticatedSubjectClass.HUMAN),
            "native_session",
            str(uuid4()),
        )

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        if request.headers.get("authorization") != "Bearer verified-native-session":
            raise AuthenticationRequired("Bearer required")
        return self.verified


class _Commands:
    def __init__(self) -> None:
        self.accept_calls: list[tuple[AuthenticatedHttpSubject, UUID, str]] = []
        self.row = StaffInvitation(
            uuid4(),
            uuid4(),
            "recipient@example.org",
            "accepted",
            1,
            2,
            datetime.now(UTC) + timedelta(days=1),
            datetime.now(UTC),
            uuid4(),
            uuid4(),
            uuid4(),
            "delivered",
        )

    async def accept(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitation:
        self.accept_calls.append((authenticated, invitation_id, token))
        return self.row

    async def list(
        self, actor: ActorContext, *, after: UUID | None, limit: int
    ) -> tuple[StaffInvitation, ...]:
        raise AssertionError("Tenant operations must not run during acceptance")

    async def get(self, actor: ActorContext, invitation_id: UUID) -> StaffInvitation:
        raise AssertionError("Tenant operations must not run during acceptance")

    async def create(
        self, actor: ActorContext, command: CreateStaffInvitationCommand
    ) -> StaffInvitation:
        raise AssertionError("Tenant operations must not run during acceptance")

    async def resend(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation:
        raise AssertionError("Tenant operations must not run during acceptance")

    async def revoke(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation:
        raise AssertionError("Tenant operations must not run during acceptance")


def _app(commands: _Commands, resolver: _Resolver) -> FastAPI:
    async def actor(request: Request) -> ActorContext:
        raise AssertionError("Acceptance must not manufacture a tenant actor")

    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(
        create_staff_invitation_router(
            commands=commands,
            authenticated_actor=actor,
            subject_resolver=resolver,
        )
    )
    return app


@pytest.mark.asyncio
async def test_acceptance_uses_verified_subject_and_no_tenant_actor() -> None:
    commands, resolver = _Commands(), _Resolver()
    app = _app(commands, resolver)
    token = f"{commands.row.invitation_id}." + "proof" * 8
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            f"/v1/staff/invitations/{commands.row.invitation_id}:accept",
            headers={"Authorization": "Bearer verified-native-session"},
            json={"token": token},
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert token not in response.text
    assert commands.accept_calls == [(resolver.verified, commands.row.invitation_id, token)]
    operation = app.openapi()["paths"]["/v1/staff/invitations/{invitation_id}:accept"]["post"]
    assert operation["operationId"] == "staff_invitation_accept"
    assert operation["security"] == [{"SubjectBearer": []}]
    assert operation["x-request-engine-owner"] == "tenancy"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status",
    [("anonymous", 401), ("tenant", 400), ("subject_selector", 422), ("short_token", 422)],
)
async def test_acceptance_rejects_untrusted_context_before_owner(case: str, status: int) -> None:
    commands, resolver = _Commands(), _Resolver()
    headers = {} if case == "anonymous" else {"Authorization": "Bearer verified-native-session"}
    body = {"token": f"{commands.row.invitation_id}." + "proof" * 8}
    if case == "tenant":
        headers["X-RE-Organization-ID"] = str(uuid4())
    if case == "subject_selector":
        body["subject_id"] = str(uuid4())
    if case == "short_token":
        body["token"] = "short-secret"
    async with AsyncClient(
        transport=ASGITransport(app=_app(commands, resolver)), base_url="https://test"
    ) as client:
        response = await client.post(
            f"/v1/staff/invitations/{commands.row.invitation_id}:accept", headers=headers, json=body
        )
    assert response.status_code == status
    assert commands.accept_calls == []
    assert body["token"] not in response.text
