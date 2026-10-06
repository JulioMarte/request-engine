"""Canonical invitation acceptance preserves the subject/tenant boundary."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.staff_invitations import (
    StaffInvitationCreateBody,
    create_staff_invitation_router,
)
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    ChangeStaffInvitationCommand,
    CreateStaffInvitationCommand,
    StaffInvitation,
    normalize_invitation_email,
)
from request_engine.modules.tenancy.application.queries.staff_invitation import (
    StaffInvitationPreview,
)
from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryError,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    RecoveryDeliveryUnavailable,
)
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.unit, pytest.mark.security]


@pytest.mark.parametrize(
    "email",
    [
        "a" * 65 + "@example.org",
        "a@invalid",
        "name@@example.org",
        "ñ@example.org",
        "a" * 64 + "@" + ".".join(["b" * 63, "c" * 63, "d" * 62]),
    ],
)
def test_invitation_email_http_and_owner_reject_same_invalid_mailboxes(email: str) -> None:
    with pytest.raises(ValueError):
        normalize_invitation_email(email)
    with pytest.raises(ValidationError):
        StaffInvitationCreateBody(email=email, provenance_reference="manual-test")


@pytest.mark.parametrize(
    "email",
    [
        "a" * 64 + "@example.org",
        "  Recipient@Example.org  ",
        "a" * 64 + "@" + ".".join(["b" * 63, "c" * 63, "d" * 61]),
    ],
)
def test_invitation_email_http_and_owner_normalize_valid_mailboxes(email: str) -> None:
    body = StaffInvitationCreateBody(email=email, provenance_reference="manual-test")
    assert body.email == normalize_invitation_email(email) == email.strip().lower()


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
        self.preview_calls: list[tuple[AuthenticatedHttpSubject, UUID, str]] = []
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

    async def preview(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitationPreview:
        self.preview_calls.append((authenticated, invitation_id, token))
        return StaffInvitationPreview(
            invitation_id,
            self.row.organization_id,
            "Engineering workspace",
            "pending",
            self.row.expires_at,
        )

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
        raise AuthenticationRequired("Tenant actor unavailable to this recipient")

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
    assert operation["security"] == [{"NativeSessionBearer": []}]
    assert operation["x-request-engine-owner"] == "tenancy"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["accept", "preview"])
@pytest.mark.parametrize(
    "case,status",
    [
        ("anonymous", 401),
        ("tenant", 400),
        ("query", 400),
        ("subject_selector", 422),
        ("short_token", 422),
    ],
)
async def test_acceptance_rejects_untrusted_context_before_owner(
    case: str, status: int, action: str
) -> None:
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
            f"/v1/staff/invitations/{commands.row.invitation_id}:{action}",
            headers=headers,
            json=body,
            params={"unexpected": "ignored"} if case == "query" else None,
        )
    assert response.status_code == status
    assert commands.accept_calls == []
    assert commands.preview_calls == []
    assert body["token"] not in response.text


@pytest.mark.asyncio
async def test_preview_is_proof_bound_minimal_advisory_post_query() -> None:
    commands, resolver = _Commands(), _Resolver()
    app = _app(commands, resolver)
    token = f"{commands.row.invitation_id}." + "proof" * 8
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        path = f"/v1/staff/invitations/{commands.row.invitation_id}:preview"
        response = await client.post(
            path, headers={"Authorization": "Bearer verified-native-session"}, json={"token": token}
        )
        rejected_get = await client.get(path, params={"token": token})
        rejected_query = await client.post(
            path,
            params={"token": token},
            headers={"Authorization": "Bearer verified-native-session"},
            json={"token": token},
        )
    assert response.status_code == 200
    assert response.json() == {
        "invitation_id": str(commands.row.invitation_id),
        "organization_id": str(commands.row.organization_id),
        "organization_display_name": "Engineering workspace",
        "status": "pending",
        "expires_at": commands.row.expires_at.isoformat().replace("+00:00", "Z"),
        "requires_acceptance_validation": True,
    }
    assert token not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert rejected_get.status_code == 401
    assert rejected_query.status_code == 400
    assert commands.accept_calls == []
    assert commands.preview_calls == [(resolver.verified, commands.row.invitation_id, token)]
    operation = app.openapi()["paths"]["/v1/staff/invitations/{invitation_id}:preview"]["post"]
    assert operation["operationId"] == "staff_invitation_preview"
    assert operation["security"] == [{"NativeSessionBearer": []}]
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"
    assert "get" not in app.openapi()["paths"]["/v1/staff/invitations/{invitation_id}:preview"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "resend", "revoke", "accept"])
@pytest.mark.parametrize(
    "error,temporary",
    [
        (RecoveryDeliveryRetryable, True),
        (RecoveryDeliveryUnavailable, False),
        (RecoveryDeliveryPermanent, False),
        (RecoveryDeliveryError, False),
    ],
)
async def test_typed_delivery_failures_preserve_safe_retry_advice_and_openapi(
    action: str,
    error: type[RecoveryDeliveryError],
    temporary: bool,
) -> None:
    commands, resolver = _Commands(), _Resolver()
    temporary = temporary and action in {"create", "resend"}
    method = AsyncMock(side_effect=error("private-provider-sentinel"))
    setattr(commands, action, method)

    async def actor(request: Request) -> ActorContext:
        return ActorContext(uuid4(), uuid4(), frozenset({"staff.invite"}))

    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(
        create_staff_invitation_router(
            commands=commands, authenticated_actor=actor, subject_resolver=resolver
        )
    )
    if action == "create":
        path = "/v1/staff/invitations"
        template = path
        body = {"email": "recipient@example.test", "provenance_reference": "test"}
    else:
        path = f"/v1/staff/invitations/{commands.row.invitation_id}:{action}"
        template = f"/v1/staff/invitations/{{invitation_id}}:{action}"
        body = {"expected_revision": 2, "provenance_reference": "test"}
        if action == "accept":
            body = {"token": str(commands.row.invitation_id) + "." + "proof" * 8}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            path,
            json=body,
            headers={
                "Idempotency-Key": "same-key",
                "Authorization": "Bearer verified-native-session",
            },
        )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"] == {
        "code": "staff_invitation_delivery_temporarily_unavailable"
        if temporary
        else "staff_invitation_delivery_unavailable",
        "message": "Staff invitation delivery is unavailable",
        "retryable": temporary,
        "resolution": "retry_same_request" if temporary else "operator_intervention",
        "details": {},
    }
    assert "private-provider-sentinel" not in response.text
    assert method.await_count == 1
    if action != "accept":
        assert method.await_args is not None
        assert method.await_args.args[1].idempotency_key == "same-key"
    responses = app.openapi()["paths"][template]["post"]["responses"]
    assert responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert {"401", "403", "404", "409", "422", "503"} <= responses.keys()
