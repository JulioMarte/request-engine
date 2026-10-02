"""Real application-role invitation semantics and real native recipient authentication."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection, Error
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
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    ChangeStaffInvitationCommand,
    CreateStaffInvitationCommand,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
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
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]


class ShortLivedInvitationStore:
    """A retained provider candidate can expire earlier than the requested TTL."""

    def __init__(self) -> None:
        self.token = ""

    async def stage(
        self, *, case_id: UUID, generation: int, secret: str, expires_at: datetime
    ) -> StagedRecoverySecret:
        del generation, expires_at
        self.token = secret
        return StagedRecoverySecret(
            f"short-lived:{case_id}",
            hashlib.sha256(secret.encode()).hexdigest(),
            datetime.now(UTC) + timedelta(seconds=2),
            True,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        del case_id, generation


@pytest.mark.asyncio
async def test_expired_proof_and_stale_revision_do_not_create_membership(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    short_store = ShortLivedInvitationStore()
    commands = PostgresStaffInvitationCommands(
        command_session_factory,
        secret_delivery=short_store,
        delivery_recorder=PostgresStaffInvitationDeliveryRecorder(),
    )
    invitation = await commands.create(
        actor,
        CreateStaffInvitationCommand("expires@example.test", "short retained proof", "expiry"),
    )
    bearer, _identity = await _recipient(command_session_factory, authority)
    deadline = monotonic() + 10
    while True:
        expiry = admin_conn.execute(
            "SELECT expires_at <= clock_timestamp() "
            "FROM request_engine.staff_invitations WHERE id=%s",
            (invitation.invitation_id,),
        ).fetchone()
        assert expiry is not None
        if expiry[0]:
            break
        assert monotonic() < deadline, "provider proof expiry was not reached"
        await asyncio.sleep(0.05)
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        denied = await client.post(
            f"/v1/staff/invitations/{invitation.invitation_id}:accept",
            headers={"Authorization": f"Bearer {bearer}"},
            json={"token": short_store.token},
        )
    assert denied.status_code == 409
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id=%s",
        (actor.organization_id,),
    ).fetchone() == (1,)
    normal = _commands(command_session_factory, InvitationSecretStore())
    replacement = await normal.create(
        actor,
        CreateStaffInvitationCommand("expires@example.test", "new onboarding", "replacement"),
    )
    assert replacement.status == "pending" and replacement.invitation_id != invitation.invitation_id
    assert (await normal.get(actor, invitation.invitation_id)).status == "expired"
    changed = await normal.resend(
        actor,
        ChangeStaffInvitationCommand(replacement.invitation_id, 1, "resend", "resend-expiry"),
    )
    with pytest.raises(StaffMembershipRevisionConflict):
        await normal.revoke(
            actor,
            ChangeStaffInvitationCommand(replacement.invitation_id, 1, "stale", "stale-expiry"),
        )
    with pytest.raises(IdempotencyConflict):
        await normal.create(
            actor,
            CreateStaffInvitationCommand("different@example.test", "new onboarding", "replacement"),
        )
    assert (await normal.get(actor, replacement.invitation_id)).revision == changed.revision


class InvitationSecretStore:
    """Only external secret backend is doubled; DB/scheduling/authentication remain real."""

    def __init__(self) -> None:
        self.secrets: dict[tuple[UUID, int], str] = {}
        self.stage_count = 0

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        self.stage_count += 1
        key = case_id, generation
        created = key not in self.secrets
        retained = self.secrets.setdefault(key, secret)
        return StagedRecoverySecret(
            f"test:{case_id}:{generation}",
            hashlib.sha256(retained.encode()).hexdigest(),
            expires_at,
            created,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.secrets.pop((case_id, generation), None)

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        raise AssertionError("Authoritative invitation commands must not send external email")

    async def reconcile(self, *, reference: str, idempotency_key: str) -> DeliveryOutcome | None:
        raise AssertionError("Authoritative invitation commands must not reconcile external email")


def _world(conn: Connection[Any]) -> tuple[ActorContext, UUID]:
    org, _party, principal, binding, _provisioner = provision_staff_root(conn)
    row = conn.execute(
        "SELECT identity_authority_id FROM request_engine.identity_bindings WHERE id=%s", (binding,)
    ).fetchone()
    assert row is not None
    return ActorContext(org, principal, frozenset({"staff.invite", "staff.read"})), row[0]


async def _recipient(sessions: SessionFactory, authority: UUID) -> tuple[str, UUID]:
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(sessions))
    handle = f"recipient-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority,
        login_handle=handle,
        password="invitation acceptance password 2026",
    )
    issued = await service.authenticate_password(
        identity_authority_id=authority,
        login_handle=handle,
        password="invitation acceptance password 2026",
    )
    return issued.raw_token, enrollment.native_identity_id


def _commands(
    sessions: SessionFactory, store: InvitationSecretStore
) -> PostgresStaffInvitationCommands:
    return PostgresStaffInvitationCommands(
        sessions, secret_delivery=store, delivery_recorder=PostgresStaffInvitationDeliveryRecorder()
    )


def _app(
    sessions: SessionFactory, commands: PostgresStaffInvitationCommands, actor: ActorContext
) -> FastAPI:
    async def resolve_actor(_request: object) -> ActorContext:
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


async def _authenticate_bearer(sessions: SessionFactory, bearer: str) -> AuthenticatedHttpSubject:
    resolver = NativeSessionHttpSubjectResolver(
        NativeSessionAuthenticator(session_reader=PostgresNativeSessionReader(sessions))
    )
    return await resolver.resolve_subject(
        Request({"type": "http", "headers": [(b"authorization", f"Bearer {bearer}".encode())]})
    )


@pytest.mark.asyncio
async def test_native_enrollment_login_acceptance_creates_zero_grant_membership(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    invitation = await commands.create(
        actor,
        CreateStaffInvitationCommand(
            " Invited.Person@Example.Test ", "help desk onboarding", "invite-1"
        ),
    )
    assert invitation.status == "pending" and invitation.email == "invited.person@example.test"
    assert invitation.membership_id is None
    bearer, identity = await _recipient(command_session_factory, authority)
    token = store.secrets[invitation.invitation_id, 1]
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        headers = {"Authorization": f"Bearer {bearer}"}
        path = f"/v1/staff/invitations/{invitation.invitation_id}:accept"
        accepted = await client.post(path, headers=headers, json={"token": token})
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result["status"] == "accepted" and result["organization_id"] == str(
            actor.organization_id
        )
        replay = await client.post(path, headers=headers, json={"token": token})
        assert replay.status_code == 200 and replay.json() == result
        other_bearer, _other_identity = await _recipient(command_session_factory, authority)
        foreign_replay = await client.post(
            path, headers={"Authorization": f"Bearer {other_bearer}"}, json={"token": token}
        )
        assert foreign_replay.status_code == 403
        duplicate = await commands.create(
            actor,
            CreateStaffInvitationCommand(
                "another-address@example.test", "existing member", "invite-existing-member"
            ),
        )
        duplicate_accept = await client.post(
            f"/v1/staff/invitations/{duplicate.invitation_id}:accept",
            headers=headers,
            json={"token": store.secrets[duplicate.invitation_id, 1]},
        )
        assert duplicate_accept.status_code == 409
        error = duplicate_accept.json()["error"]
        assert error["code"] == "staff_invitation_identity_already_linked"
        assert error["retryable"] is False
        assert error["resolution"] == "request_authority"
        assert "existing membership and permissions" in error["message"]
        assert "resending an invitation will not restore access" in error["message"]
        assert admin_conn.execute(
            "SELECT status,membership_id FROM request_engine.staff_invitations WHERE id=%s",
            (duplicate.invitation_id,),
        ).fetchone() == ("pending", None)
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id=%s",
            (actor.organization_id,),
        ).fetchone() == (2,)
    principal = UUID(result["principal_id"])
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants WHERE principal_id=%s",
        (principal,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT status,revision,accepted_native_identity_id "
        "FROM request_engine.staff_invitations WHERE id=%s",
        (invitation.invitation_id,),
    ).fetchone() == ("accepted", 2, identity)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE aggregate_id=%s AND command_name='staff.invitation.accept'",
        (invitation.invitation_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.staff_invitation_deliveries WHERE invitation_id=%s",
        (invitation.invitation_id,),
    ).fetchone() == ("cancelled",)


@pytest.mark.asyncio
async def test_resend_rotates_token_and_replay_after_revoke_never_stages_again(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    create = CreateStaffInvitationCommand("join@example.test", "onboarding", "create")
    invitation = await commands.create(actor, create)
    old = store.secrets[invitation.invitation_id, 1]
    changed = await commands.resend(
        actor,
        ChangeStaffInvitationCommand(
            invitation.invitation_id, invitation.revision, "resend requested", "resend"
        ),
    )
    assert changed.revision == 2 and changed.generation == 2
    bearer, _identity = await _recipient(command_session_factory, authority)
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        result = await client.post(
            f"/v1/staff/invitations/{invitation.invitation_id}:accept",
            headers={"Authorization": f"Bearer {bearer}"},
            json={"token": old},
        )
        assert result.status_code == 404
    revoked = await commands.revoke(
        actor,
        ChangeStaffInvitationCommand(
            invitation.invitation_id, changed.revision, "cancel onboarding", "revoke"
        ),
    )
    stages = store.stage_count
    replay = await commands.create(actor, create)
    assert replay.invitation_id == revoked.invitation_id and replay.status == "revoked"
    assert store.stage_count == stages
    audit_rows = admin_conn.execute(
        "SELECT details->>'action',details->>'provenance_reference' "
        "FROM request_engine.audit_records WHERE aggregate_id=%s ORDER BY created_at,id",
        (invitation.invitation_id,),
    ).fetchall()
    assert audit_rows == [
        ("create", "onboarding"),
        ("resend", "resend requested"),
        ("revoke", "cancel onboarding"),
    ]
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id=%s",
        (actor.organization_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_inviter_authority_withdrawal_denies_acceptance_without_effects(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    invitation = await commands.create(
        actor, CreateStaffInvitationCommand("join@example.test", "onboarding", "create")
    )
    bearer, _identity = await _recipient(command_session_factory, authority)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked',revision=revision+1,"
        "revoked_at=clock_timestamp(),revoked_by_principal_id=principal_id "
        "WHERE principal_id=%s AND capability_key='staff.invite' AND status='active'",
        (actor.principal_id,),
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(command_session_factory, commands, actor)),
        base_url="http://test",
    ) as client:
        result = await client.post(
            f"/v1/staff/invitations/{invitation.invitation_id}:accept",
            headers={"Authorization": f"Bearer {bearer}"},
            json={"token": store.secrets[invitation.invitation_id, 1]},
        )
        assert result.status_code == 403, result.text
    assert admin_conn.execute(
        "SELECT status,membership_id FROM request_engine.staff_invitations WHERE id=%s",
        (invitation.invitation_id,),
    ).fetchone() == ("pending", None)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id=%s",
        (actor.organization_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_app_role_cannot_forge_acceptance_gucs_or_direct_terminal_transition(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    app_role_conn: Connection[Any],
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    invitation = await commands.create(
        actor, CreateStaffInvitationCommand("join@example.test", "onboarding", "create")
    )
    with pytest.raises(Error) as failure, app_role_conn.transaction():
        app_role_conn.execute(
            "SELECT set_config('request_engine.staff_invitation_id',%s,true),"
            "set_config('request_engine.staff_invitation_subject',%s,true)",
            (str(invitation.invitation_id), str(uuid4())),
        )
        app_role_conn.execute(
            "SELECT request_cmd.materialize_invited_staff(%s,NULL,%s,%s,%s,%s,%s,%s)",
            (invitation.invitation_id, authority, uuid4(), uuid4(), uuid4(), uuid4(), uuid4()),
        )
    assert failure.value.sqlstate == "P0002"
    with pytest.raises(Error) as forbidden, app_role_conn.transaction():
        app_role_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true)",
            (str(actor.organization_id),),
        )
        app_role_conn.execute(
            "UPDATE request_engine.staff_invitations SET status='accepted',"
            "revision=revision+1 WHERE id=%s",
            (invitation.invitation_id,),
        )
    assert forbidden.value.sqlstate == "42501"
    with pytest.raises(Error) as rewritten, app_role_conn.transaction():
        app_role_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true)",
            (str(actor.organization_id),),
        )
        app_role_conn.execute(
            "UPDATE request_engine.staff_invitations SET status='revoked',revision=revision+1,"
            "provenance_reference='rewritten history' WHERE id=%s",
            (invitation.invitation_id,),
        )
    assert rewritten.value.sqlstate == "23514"
    with app_role_conn.transaction():
        assert app_role_conn.execute(
            "SELECT request_auth.staff_invitation_target(%s,%s)",
            (invitation.invitation_id, "0" * 64),
        ).fetchone() == (None,)
        assert app_role_conn.execute(
            "SELECT request_auth.staff_invitation_target(%s,NULL)", (invitation.invitation_id,)
        ).fetchone() == (None,)
    assert admin_conn.execute(
        "SELECT status,membership_id FROM request_engine.staff_invitations WHERE id=%s",
        (invitation.invitation_id,),
    ).fetchone() == ("pending", None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email",
    [
        "victim@example.test,other",
        "Person <victim@example.test>",
        "victim@example.test;other@example.test",
        "victim@example.test\r\nBcc: other@example.test",
        '"quoted"@example.test',
        "tést@example.test",
        "a..b@example.test",
        "a@-example.test",
    ],
)
async def test_invitation_rejects_recipient_lists_headers_and_unsupported_mailboxes_before_staging(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    email: str,
) -> None:
    actor, _authority = _world(admin_conn)
    store = InvitationSecretStore()
    with pytest.raises(StaffMembershipInputInvalid):
        await _commands(command_session_factory, store).create(
            actor, CreateStaffInvitationCommand(email, "onboarding", "invalid-address")
        )
    assert store.stage_count == 0
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_invitations WHERE organization_id=%s",
        (actor.organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_revoked_native_session_between_authentication_and_acceptance_fails_closed(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    invitation = await commands.create(
        actor, CreateStaffInvitationCommand("recipient@example.test", "onboarding", "create")
    )
    bearer, identity = await _recipient(command_session_factory, authority)
    authenticated = await _authenticate_bearer(command_session_factory, bearer)
    assert authenticated.credential_id is not None
    await NativeHumanAuthService(
        store=PostgresNativeHumanAuthStore(command_session_factory)
    ).revoke_session(native_identity_id=identity, session_id=UUID(authenticated.credential_id))
    with pytest.raises(StaffMembershipForbidden):
        await commands.accept(
            authenticated, invitation.invitation_id, store.secrets[invitation.invitation_id, 1]
        )
    assert admin_conn.execute(
        "SELECT status,membership_id FROM request_engine.staff_invitations WHERE id=%s",
        (invitation.invitation_id,),
    ).fetchone() == ("pending", None)


class PausedCancellation(PostgresStaffInvitationDeliveryRecorder):
    """Deterministic synchronization after real owner cancellation, before lifecycle commit."""

    def __init__(self, reached: asyncio.Event, release: asyncio.Event) -> None:
        self.reached = reached
        self.release = release

    async def cancel(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        invitation_id: UUID,
    ) -> None:
        await super().cancel(
            transaction, organization_id=organization_id, invitation_id=invitation_id
        )
        self.reached.set()
        await asyncio.wait_for(self.release.wait(), timeout=15)


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("action", ["revoke", "resend"])
async def test_acceptance_races_revisioned_lifecycle_on_independent_real_transactions(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    action: str,
) -> None:
    actor, authority = _world(admin_conn)
    store = InvitationSecretStore()
    normal = _commands(command_session_factory, store)
    invitation = await normal.create(
        actor, CreateStaffInvitationCommand("recipient@example.test", "onboarding", "create")
    )
    bearer, _identity = await _recipient(command_session_factory, authority)
    authenticated = await _authenticate_bearer(command_session_factory, bearer)
    reached, release = asyncio.Event(), asyncio.Event()
    changing = PostgresStaffInvitationCommands(
        command_session_factory,
        secret_delivery=store,
        delivery_recorder=PausedCancellation(reached, release),
    )
    command = ChangeStaffInvitationCommand(
        invitation.invitation_id, 1, "onboarding changed", action
    )
    lifecycle = asyncio.create_task(
        changing.revoke(actor, command) if action == "revoke" else changing.resend(actor, command)
    )
    await asyncio.wait_for(reached.wait(), timeout=10)
    acceptance = asyncio.create_task(
        normal.accept(
            authenticated, invitation.invitation_id, store.secrets[invitation.invitation_id, 1]
        )
    )
    try:
        deadline = monotonic() + 10
        while True:
            blocked = admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type='Lock' "
                "AND query LIKE '%%request_cmd.lock_staff_invitation_acceptance%%'"
            ).fetchone()
            if blocked is not None and blocked[0] > 0:
                break
            assert not acceptance.done(), "Acceptance must wait on the held authoritative lock"
            assert monotonic() < deadline, (
                "Independent acceptance transaction was not observed blocked"
            )
            await asyncio.sleep(0.01)
        # Synchronization depends on observed PostgreSQL contention, not elapsed sleep.
        release.set()
        changed = await lifecycle
        with pytest.raises(
            StaffMembershipConflict if action == "revoke" else StaffMembershipNotFound
        ):
            await acceptance
        assert changed.revision == 2
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id=%s",
            (actor.organization_id,),
        ).fetchone() == (1,)
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.audit_records "
            "WHERE aggregate_id=%s AND command_name='staff.invitation.accept'",
            (invitation.invitation_id,),
        ).fetchone() == (0,)
    finally:
        release.set()
        await asyncio.gather(lifecycle, acceptance, return_exceptions=True)
