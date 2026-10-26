"""Shareable-link staff invitations on the real application role (INV-STAFF-INVITATION-LINK-001).

Plausible defects caught: the raw proof persisted anywhere in PostgreSQL (row,
audit, idempotency receipt, delivery intent), the proof returned again by a read
or an idempotent replay, link delivery still requiring the email secret store,
a link resend leaving the previous proof (or a queued email) usable, and the
audit not recording that a shareable link was issued. Only the external email
secret backend is doubled; DB, idempotency and native recipient auth are real.
"""

import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from test_staff_membership_lifecycle import provision_staff_root

from request_engine.modules.communications.adapters.db.staff_invitation_delivery import (
    PostgresStaffInvitationDeliveryRecorder,
)
from request_engine.modules.tenancy.adapters.db.staff_invitation_commands import (
    PostgresStaffInvitationCommands,
)
from request_engine.modules.tenancy.api.staff_invitations import create_staff_invitation_router
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.secrets.delivery import DeliveryOutcome, StagedRecoverySecret
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.native_http import NativeSessionHttpSubjectResolver
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]
PgConnection = Connection[Any]
_ACCEPT_URL = "http://localhost:8002/staff-invitations"


class _EmailSecretStore:
    """External email proof backend double; never sends."""

    def __init__(self) -> None:
        self.stage_count = 0

    async def stage(
        self, *, case_id: UUID, generation: int, secret: str, expires_at: datetime
    ) -> StagedRecoverySecret:
        self.stage_count += 1
        return StagedRecoverySecret(
            f"test:{case_id}:{generation}",
            hashlib.sha256(secret.encode()).hexdigest(),
            expires_at,
            True,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        return None

    async def publish(
        self, *, reference: str, destination_reference: str, idempotency_key: str
    ) -> DeliveryOutcome:
        raise AssertionError("commands must not send email")

    async def reconcile(self, *, reference: str, idempotency_key: str) -> DeliveryOutcome | None:
        raise AssertionError("commands must not reconcile email")


def _world(conn: PgConnection) -> tuple[ActorContext, UUID]:
    org, _party, principal, binding, _provisioner = provision_staff_root(conn)
    row = conn.execute(
        "SELECT identity_authority_id FROM request_engine.identity_bindings WHERE id=%s", (binding,)
    ).fetchone()
    assert row is not None
    return ActorContext(org, principal, frozenset({"staff.invite", "staff.read"})), row[0]


def _app(
    sessions: SessionFactory, commands: PostgresStaffInvitationCommands, actor: ActorContext
) -> FastAPI:
    async def resolve_actor(_request: Request) -> ActorContext:
        return actor

    resolver = NativeSessionHttpSubjectResolver(
        NativeSessionAuthenticator(session_reader=PostgresNativeSessionReader(sessions))
    )
    app = FastAPI()
    add_staff_membership_error_handlers(app)
    app.include_router(
        create_staff_invitation_router(
            commands=commands, authenticated_actor=resolve_actor, subject_resolver=resolver
        )
    )
    return app


async def _recipient_bearer(sessions: SessionFactory, authority: UUID) -> str:
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(sessions))
    handle = f"whatsapp-recipient-{uuid4().hex}@example.test"
    await service.enroll_password_identity(
        identity_authority_id=authority, login_handle=handle, password="link invitation pw 2026"
    )
    issued = await service.authenticate_password(
        identity_authority_id=authority, login_handle=handle, password="link invitation pw 2026"
    )
    return issued.raw_token


def _persisted_text(conn: PgConnection, organization_id: UUID) -> str:
    rows = conn.execute(
        """
        SELECT row_to_json(i)::text FROM request_engine.staff_invitations i
         WHERE organization_id = %s
        UNION ALL SELECT details::text FROM request_engine.audit_records
         WHERE organization_id = %s
        UNION ALL SELECT COALESCE(result_data::text, '') FROM request_engine.idempotency_records
         WHERE organization_id = %s
        UNION ALL SELECT row_to_json(d)::text FROM request_engine.staff_invitation_deliveries d
         WHERE organization_id = %s
        """,
        (organization_id,) * 4,
    ).fetchall()
    return "\n".join(str(row[0]) for row in rows)


@pytest.mark.asyncio
async def test_link_invitation_returns_proof_once_and_persists_only_its_digest(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    # No email secret store and no delivery recorder: link delivery must not need them.
    commands = PostgresStaffInvitationCommands(
        command_session_factory,
        secret_delivery=None,
        delivery_recorder=None,
        acceptance_url=_ACCEPT_URL,
    )
    body = {"email": "nueva.recepcionista@example.test", "provenance_reference": "whatsapp"}
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        email_only = await client.post(
            "/v1/staff/invitations",
            headers={"Idempotency-Key": "email-without-store"},
            json={**body, "email": "other@example.test"},
        )
        assert email_only.status_code == 503, email_only.text
        assert email_only.json()["error"]["code"] == "staff_invitation_delivery_unavailable"

        key = {"Idempotency-Key": "link-create"}
        created = await client.post(
            "/v1/staff/invitations", headers=key, json={**body, "delivery": "link"}
        )
        assert created.status_code == 201, created.text
        assert created.headers["cache-control"] == "no-store"
        view = created.json()
        invitation_id = UUID(view["invitation_id"])
        token = view["acceptance_token"]
        assert isinstance(token, str) and token.startswith(f"{invitation_id}.")
        assert view["acceptance_url"] == (
            f"{_ACCEPT_URL}/{invitation_id}/accept#token={quote(token, safe='')}"
        )
        assert view["delivery_channel"] == "link" and view["delivery_status"] is None

        replay = await client.post(
            "/v1/staff/invitations", headers=key, json={**body, "delivery": "link"}
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["invitation_id"] == str(invitation_id)
        assert replay.json()["acceptance_token"] is None
        assert replay.json()["acceptance_url"] is None
        # The channel is part of the command intent: reusing the key for email conflicts.
        with pytest.raises(IdempotencyConflict):
            await client.post(
                "/v1/staff/invitations", headers=key, json={**body, "delivery": "email"}
            )
        read = await client.get(f"/v1/staff/invitations/{invitation_id}")
        assert read.status_code == 200 and read.json()["acceptance_token"] is None
        assert read.json()["delivery_channel"] == "link"

        persisted = _persisted_text(admin_conn, actor.organization_id)
        assert token not in persisted
        assert token.partition(".")[2] not in persisted
        assert admin_conn.execute(
            "SELECT token_digest, delivery_channel FROM request_engine.staff_invitations"
            " WHERE id = %s",
            (invitation_id,),
        ).fetchone() == (hashlib.sha256(token.encode()).hexdigest(), "link")
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.staff_invitation_deliveries"
            " WHERE invitation_id = %s",
            (invitation_id,),
        ).fetchone() == (0,)
        assert admin_conn.execute(
            "SELECT details->>'delivery_channel', details->>'shareable_link_issued'"
            " FROM request_engine.audit_records WHERE aggregate_id = %s"
            " AND command_name = 'staff.invitation.create'",
            (invitation_id,),
        ).fetchall() == [("link", "true")]

        # A link resend rotates the proof; the previous one stops working.
        resent = await client.post(
            f"/v1/staff/invitations/{invitation_id}:resend",
            headers={"Idempotency-Key": "link-resend"},
            json={"expected_revision": 1, "provenance_reference": "lost", "delivery": "link"},
        )
        assert resent.status_code == 200, resent.text
        assert resent.headers["cache-control"] == "no-store"
        new_token = resent.json()["acceptance_token"]
        assert new_token and new_token != token and resent.json()["generation"] == 2

        bearer = await _recipient_bearer(command_session_factory, authority)
        auth = {"Authorization": f"Bearer {bearer}"}
        accept_path = f"/v1/staff/invitations/{invitation_id}:accept"
        stale = await client.post(accept_path, headers=auth, json={"token": token})
        assert stale.status_code == 404, stale.text
        accepted = await client.post(accept_path, headers=auth, json={"token": new_token})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"
        assert accepted.json()["acceptance_token"] is None
    principal = UUID(accepted.json()["principal_id"])
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants WHERE principal_id=%s",
        (principal,),
    ).fetchone() == (0,)
    persisted = _persisted_text(admin_conn, actor.organization_id)
    assert new_token not in persisted and token not in persisted


@pytest.mark.asyncio
async def test_switching_an_email_invitation_to_link_cancels_the_queued_email(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    actor, _authority = _world(admin_conn)
    store = _EmailSecretStore()
    commands = PostgresStaffInvitationCommands(
        command_session_factory,
        secret_delivery=store,
        delivery_recorder=PostgresStaffInvitationDeliveryRecorder(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/staff/invitations",
            headers={"Idempotency-Key": "email-first"},
            json={"email": "doctor@example.test", "provenance_reference": "email first"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["acceptance_token"] is None
        assert created.json()["delivery_channel"] == "email"
        invitation_id = created.json()["invitation_id"]
        resent = await client.post(
            f"/v1/staff/invitations/{invitation_id}:resend",
            headers={"Idempotency-Key": "switch-to-link"},
            json={"expected_revision": 1, "provenance_reference": "share", "delivery": "link"},
        )
        assert resent.status_code == 200, resent.text
        assert resent.json()["acceptance_token"] and resent.json()["acceptance_url"] is None
    assert store.stage_count == 1
    assert admin_conn.execute(
        "SELECT generation, status FROM request_engine.staff_invitation_deliveries"
        " WHERE invitation_id = %s ORDER BY generation",
        (UUID(invitation_id),),
    ).fetchall() == [(1, "cancelled")]
    assert admin_conn.execute(
        "SELECT delivery_channel, generation FROM request_engine.staff_invitations WHERE id = %s",
        (UUID(invitation_id),),
    ).fetchone() == ("link", 2)
