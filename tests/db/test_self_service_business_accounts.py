"""Self-service business owner accounts on real PostgreSQL 18 (ADR 0021).

Protected guarantee: INV-SELF-SERVICE-ACCOUNT-001 (plus INV-IDEMPOTENCY-001,
INV-PRIVILEGE-001). Plausible defects these proofs must catch: a limit checked
without the entitlement lock (two winners for one slot), a replay that creates a
second organization, a revoked/expired/used or issuer-revoked code that still
enrolls, a stale session that still creates, platform authority leaking into the
tenant or the runtime role reading private account tables directly.
"""

import asyncio
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from platform_provisioning_support import platform_grant, platform_principal, principal_revision
from psycopg import Connection, sql
from psycopg.errors import CheckViolation, InsufficientPrivilege

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.account_invitation_commands import (
    PostgresPlatformAccountInvitationCommands,
)
from request_engine.modules.tenancy.adapters.db.self_service_account_commands import (
    PostgresSelfServiceAccountCommands,
)
from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountInvitationConflict,
    AccountInvitationDeliveryUnavailable,
    AccountInvitationInvalid,
    AccountInvitationRevisionConflict,
    AccountLoginUnavailable,
    CreateAccountInvitationCommand,
    EnrollAccountInvitationCommand,
    RevokeAccountInvitationCommand,
)
from request_engine.modules.tenancy.application.commands.self_service_organizations import (
    CreateSelfServiceOrganizationCommand,
    SelfServiceOrganizationCreated,
    SelfServiceOrganizationForbidden,
    SelfServiceOrganizationIdempotencyConflict,
    SelfServiceOrganizationKeyUnavailable,
    SelfServiceOrganizationLimitReached,
)
from request_engine.modules.tenancy.domain.account_entitlement import AccountInvitationDelivery
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import DeliveryOutcome
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]
PgConnection = Connection[Any]
PASSWORD = "owner chosen proof password"


class RecordingMailer:
    def __init__(self, outcome: DeliveryOutcome) -> None:
        self.outcome = outcome
        self.sent: list[tuple[str, str]] = []

    async def send(
        self, *, secret: str, destination_reference: str, idempotency_key: str
    ) -> DeliveryOutcome:
        self.sent.append((secret, destination_reference))
        return self.outcome


def _issuer(conn: PgConnection) -> PlatformActorContext:
    principal = platform_principal(conn)
    for capability in ("organization.provision", "platform.organization.read"):
        platform_grant(conn, principal_id=principal, capability=capability, delegable=True)
    return PlatformActorContext(
        principal_id=principal,
        authority_revision=principal_revision(conn, principal),
        capabilities=frozenset({"organization.provision", "platform.organization.read"}),
    )


def _authority(conn: PgConnection) -> UUID:
    authority = uuid4()
    conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority, f"self-service-{authority}"),
    )
    return authority


def _invite(max_organizations: int = 1, key: str = "invite-1") -> CreateAccountInvitationCommand:
    return CreateAccountInvitationCommand(
        delivery=AccountInvitationDelivery.SHARED_CODE,
        email=None,
        max_organizations=max_organizations,
        expires_in_hours=72,
        provenance_reference="sales:whatsapp-lead",
        idempotency_key=key,
    )


async def _subject(
    sessions: SessionFactory, authority: UUID, login: str
) -> AuthenticatedHttpSubject:
    issued = await build_native_auth_runtime(sessions).service.authenticate_password(
        identity_authority_id=authority, login_handle=login, password=PASSWORD
    )
    return AuthenticatedHttpSubject(
        subject=AuthenticatedSubject(
            authority_id=str(authority),
            subject_id=str(issued.native_identity_id),
            subject_class=AuthenticatedSubjectClass.HUMAN,
        ),
        authentication_method="native_session",
        credential_id=str(issued.session_id),
    )


async def _enrolled_owner(
    conn: PgConnection,
    command_sessions: SessionFactory,
    control_sessions: SessionFactory,
    read_sessions: SessionFactory,
    *,
    max_organizations: int = 1,
    login: str = "owner@example.test",
) -> tuple[PlatformActorContext, UUID, PostgresSelfServiceAccountCommands]:
    issuer = _issuer(conn)
    authority = _authority(conn)
    invitations = PostgresPlatformAccountInvitationCommands(
        control_sessions, read_sessions, mailer=None
    )
    issued = await invitations.create(issuer, _invite(max_organizations))
    assert issued.raw_token is not None
    owner = PostgresSelfServiceAccountCommands(command_sessions, native_authority_id=authority)
    await owner.enroll(
        EnrollAccountInvitationCommand(
            raw_token=issued.raw_token, login_handle=login, password=PASSWORD
        )
    )
    return issuer, authority, owner


@pytest.mark.asyncio
async def test_invite_enroll_create_is_atomic_idempotent_and_bounded(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    issuer = _issuer(admin_conn)
    authority = _authority(admin_conn)
    invitations = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory, platform_read_session_factory, mailer=None
    )
    issued = await invitations.create(issuer, _invite())
    assert issued.created and issued.raw_token is not None and issued.status == "pending"
    replay = await invitations.create(issuer, _invite())
    assert (replay.invitation_id, replay.created, replay.raw_token) == (
        issued.invitation_id,
        False,
        None,
    )
    with pytest.raises(AccountInvitationConflict):
        await invitations.create(issuer, replace(_invite(), max_organizations=2))
    stored = admin_conn.execute(
        "SELECT token_digest, status FROM request_engine.account_invitations"
    ).fetchall()
    assert len(stored) == 1 and stored[0][1] == "pending"
    assert issued.raw_token.encode() not in bytes(stored[0][0])

    owner = PostgresSelfServiceAccountCommands(
        command_session_factory, native_authority_id=authority
    )
    enrolled = await owner.enroll(
        EnrollAccountInvitationCommand(
            raw_token=issued.raw_token, login_handle=" Owner@Example.TEST ", password=PASSWORD
        )
    )
    assert enrolled.login_handle == "owner@example.test" and enrolled.max_organizations == 1
    with pytest.raises(AccountInvitationInvalid):  # single use
        await owner.enroll(
            EnrollAccountInvitationCommand(
                raw_token=issued.raw_token, login_handle="other@example.test", password=PASSWORD
            )
        )
    subject = await _subject(command_session_factory, authority, "owner@example.test")
    entitlement = await owner.read_entitlement(subject)
    assert entitlement is not None and entitlement.remaining == 1

    command = CreateSelfServiceOrganizationCommand(
        display_name="Clínica Dental Sonrisa", idempotency_key="wizard-1"
    )
    created = await owner.create_organization(subject, command)
    assert created.created and created.organizations_created == 1
    assert created.organization_key.startswith("clinica-dental-sonrisa-")
    assert (created.default_timezone, created.default_locale, created.default_currency) == (
        "America/Santo_Domingo",
        "es-DO",
        "DOP",
    )
    assert created.initial_controller_policy == "tenant-controller-v10"
    again = await owner.create_organization(subject, command)
    assert again == replace(created, created=False)
    with pytest.raises(SelfServiceOrganizationIdempotencyConflict):
        await owner.create_organization(subject, replace(command, display_name="Otra Clínica"))
    with pytest.raises(SelfServiceOrganizationLimitReached):
        await owner.create_organization(subject, replace(command, idempotency_key="wizard-2"))

    org = created.organization_id
    assert admin_conn.execute(
        "SELECT display_name, default_timezone, default_locale, default_currency "
        "FROM request_engine.organizations"
    ).fetchall() == [("Clínica Dental Sonrisa", "America/Santo_Domingo", "es-DO", "DOP")]
    assert admin_conn.execute(
        "SELECT provisioned_by_principal_id, controller_principal_id, "
        "initial_controller_policy_key FROM request_engine.organization_root_provisioning_facts"
    ).fetchone() == (issuer.principal_id, created.controller_principal_id, "tenant-controller-v10")
    assert admin_conn.execute(
        "SELECT organization_id, principal_plane, external_subject FROM request_engine.principals "
        "WHERE id=%s",
        (created.controller_principal_id,),
    ).fetchone() == (org, "tenant", f"native:{enrolled.native_identity_id}")
    # Independent oracle: the immutable v10 manifest decides the policy grants.
    policy_grants = admin_conn.execute(
        "SELECT jsonb_array_length(grants) FROM request_engine.initial_controller_policies "
        "WHERE policy_key='tenant-controller-v10'"
    ).fetchone()
    policy_seeded = admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND status='active' AND provenance_reference LIKE 'policy:%%'",
        (created.controller_principal_id,),
    ).fetchone()
    assert policy_seeded == policy_grants
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND authority_plane='platform'",
        (created.controller_principal_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT id, status FROM request_engine.staff_memberships WHERE organization_id=%s",
        (org,),
    ).fetchall() == [(created.membership_id, "active")]
    # The issuing platform Principal never becomes tenant staff or gains tenant grants.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND organization_id IS NOT NULL",
        (issuer.principal_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT native_identity_id, sequence FROM request_engine.account_organization_creations"
    ).fetchall() == [(enrolled.native_identity_id, 1)]
    assert admin_conn.execute(
        "SELECT action FROM request_engine.account_invitation_facts ORDER BY created_at"
    ).fetchall() == [("create",), ("accept",)]
    # Database backstop independent of the function's own limit check.
    with pytest.raises(CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.account_entitlements SET organizations_created=2, "
            "revision=revision+1"
        )
    listed = await invitations.list(issuer, invitation_id=None, after=None, limit=10)
    assert [(row.status, row.organizations_created) for row in listed] == [("accepted", 1)]


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_creations_never_exceed_the_entitlement_limit(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    _, authority, owner = await _enrolled_owner(
        admin_conn,
        command_session_factory,
        platform_control_session_factory,
        platform_read_session_factory,
        max_organizations=2,
    )
    subject = await _subject(command_session_factory, authority, "owner@example.test")
    commands = [
        CreateSelfServiceOrganizationCommand(
            display_name=f"Negocio {index}", idempotency_key=f"race-{index}"
        )
        for index in range(3)
    ]
    # Hold the serialization root from an independent connection, start three
    # independent command transactions and release only after PostgreSQL reports
    # all three blocked on a lock: the limit must be decided under the row lock.
    locker = PgConnection.connect(pg_conninfo)
    locker.execute("SELECT id FROM request_engine.account_entitlements FOR UPDATE")
    tasks = [asyncio.create_task(owner.create_organization(subject, c)) for c in commands]
    try:
        deadline = asyncio.get_running_loop().time() + 15
        while True:
            waiting = admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND usename LIKE 'request_engine_app_f3_%%' AND wait_event_type='Lock'"
            ).fetchone()
            if waiting == (3,):
                break
            assert not any(task.done() for task in tasks), "creation bypassed the lock root"
            assert asyncio.get_running_loop().time() < deadline, "all creations must contend"
            await asyncio.sleep(0.01)
    finally:
        locker.rollback()
        locker.close()
        outcomes = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=30
        )
    winners = [o for o in outcomes if isinstance(o, SelfServiceOrganizationCreated)]
    losers = [o for o in outcomes if isinstance(o, SelfServiceOrganizationLimitReached)]
    assert (len(winners), len(losers)) == (2, 1), outcomes
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.organizations"
    ).fetchone() == (2,)
    assert admin_conn.execute(
        "SELECT organizations_created, revision FROM request_engine.account_entitlements"
    ).fetchone() == (2, 3)
    assert sorted(
        row[0]
        for row in admin_conn.execute(
            "SELECT sequence FROM request_engine.account_organization_creations"
        ).fetchall()
    ) == [1, 2]


@pytest.mark.asyncio
async def test_revoked_expired_and_issuer_revoked_codes_never_enroll(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    issuer = _issuer(admin_conn)
    authority = _authority(admin_conn)
    invitations = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory, platform_read_session_factory, mailer=None
    )
    owner = PostgresSelfServiceAccountCommands(
        command_session_factory, native_authority_id=authority
    )

    def enroll(token: str, login: str) -> EnrollAccountInvitationCommand:
        return EnrollAccountInvitationCommand(
            raw_token=token, login_handle=login, password=PASSWORD
        )

    revoked = await invitations.create(issuer, _invite(key="revoked"))
    assert revoked.raw_token is not None
    revoke = RevokeAccountInvitationCommand(
        invitation_id=revoked.invitation_id,
        expected_revision=1,
        reason_code="sent_to_wrong_person",
        idempotency_key="revoke-1",
    )
    with pytest.raises(AccountInvitationRevisionConflict):
        await invitations.revoke(issuer, replace(revoke, expected_revision=7))
    result = await invitations.revoke(issuer, revoke)
    assert (result.status, result.revision) == ("revoked", 2)
    assert await invitations.revoke(issuer, revoke) == result  # idempotent replay
    with pytest.raises(AccountInvitationConflict):
        await invitations.revoke(issuer, replace(revoke, idempotency_key="revoke-2"))
    with pytest.raises(AccountInvitationInvalid):
        await owner.enroll(enroll(revoked.raw_token, "revoked@example.test"))

    expired = await invitations.create(issuer, _invite(key="expired"))
    assert expired.raw_token is not None
    admin_conn.execute(  # time travel only: the row keeps its own state machine
        "UPDATE request_engine.account_invitations SET created_at=now()-interval '3 days', "
        "expires_at=now()-interval '1 second' WHERE id=%s",
        (expired.invitation_id,),
    )
    with pytest.raises(AccountInvitationInvalid):
        await owner.enroll(enroll(expired.raw_token, "expired@example.test"))
    listed = await invitations.list(
        issuer, invitation_id=expired.invitation_id, after=None, limit=1
    )
    assert listed[0].expired is True and listed[0].status == "pending"

    orphaned = await invitations.create(issuer, _invite(key="orphaned"))
    assert orphaned.raw_token is not None
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='organization.provision'",
        (platform_principal(admin_conn), issuer.principal_id),
    )
    with pytest.raises(AccountInvitationInvalid):
        await owner.enroll(enroll(orphaned.raw_token, "orphaned@example.test"))
    with pytest.raises(AccountInvitationInvalid):
        await owner.enroll(enroll("x" * 43, "guess@example.test"))
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities"
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.account_entitlements"
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_existing_login_stale_session_and_unentitled_identity_are_refused(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    issuer, authority, owner = await _enrolled_owner(
        admin_conn,
        command_session_factory,
        platform_control_session_factory,
        platform_read_session_factory,
    )
    invitations = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory, platform_read_session_factory, mailer=None
    )
    second = await invitations.create(issuer, _invite(key="second"))
    assert second.raw_token is not None
    with pytest.raises(AccountLoginUnavailable):
        await owner.enroll(
            EnrollAccountInvitationCommand(
                raw_token=second.raw_token, login_handle="owner@example.test", password=PASSWORD
            )
        )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.account_invitations WHERE id=%s",
        (second.invitation_id,),
    ).fetchone() == ("pending",)

    runtime = build_native_auth_runtime(command_session_factory)
    stranger = await runtime.service.enroll_password_identity(
        identity_authority_id=authority, login_handle="stranger@example.test", password=PASSWORD
    )
    command = CreateSelfServiceOrganizationCommand(display_name="Sin permiso", idempotency_key="k")
    stranger_subject = await _subject(command_session_factory, authority, "stranger@example.test")
    assert await owner.read_entitlement(stranger_subject) is None
    with pytest.raises(SelfServiceOrganizationForbidden):
        await owner.create_organization(stranger_subject, command)

    subject = await _subject(command_session_factory, authority, "owner@example.test")
    await runtime.service.revoke_session(
        native_identity_id=UUID(subject.subject.subject_id),
        session_id=UUID(str(subject.credential_id)),
    )
    with pytest.raises(SelfServiceOrganizationForbidden):
        await owner.create_organization(subject, command)
    fresh = await _subject(command_session_factory, authority, "owner@example.test")
    taken = CreateSelfServiceOrganizationCommand(
        display_name="Dup", idempotency_key="dup", organization_key="taken-key"
    )
    admin_conn.execute(
        "INSERT INTO request_engine.organizations(organization_key, display_name) "
        "VALUES ('taken-key', 'Existing')"
    )
    with pytest.raises(SelfServiceOrganizationKeyUnavailable):
        await owner.create_organization(fresh, taken)
    assert admin_conn.execute(
        "SELECT organizations_created FROM request_engine.account_entitlements"
    ).fetchone() == (0,)
    assert stranger.native_identity_id is not None


@pytest.mark.asyncio
async def test_email_invitations_send_once_after_commit_or_fail_closed(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    issuer = _issuer(admin_conn)
    email = replace(
        _invite(key="email"), delivery=AccountInvitationDelivery.EMAIL, email="Dueno@Example.TEST"
    )
    unconfigured = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory, platform_read_session_factory, mailer=None
    )
    with pytest.raises(AccountInvitationDeliveryUnavailable):
        await unconfigured.create(issuer, email)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.account_invitations"
    ).fetchone() == (0,)

    mailer = RecordingMailer(DeliveryOutcome.DELIVERED)
    commands = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory, platform_read_session_factory, mailer=mailer
    )
    issued = await commands.create(issuer, email)
    assert issued.raw_token is None and issued.delivery_status == "sent"
    replay = await commands.create(issuer, email)
    assert replay.delivery_status == "sent" and len(mailer.sent) == 1
    assert mailer.sent[0][1] == "dueno@example.test" and len(mailer.sent[0][0]) >= 40
    assert admin_conn.execute(
        "SELECT action, delivery_status FROM request_engine.account_invitation_facts "
        "ORDER BY created_at"
    ).fetchall() == [("create", None), ("delivery", "sent")]

    failing = PostgresPlatformAccountInvitationCommands(
        platform_control_session_factory,
        platform_read_session_factory,
        mailer=RecordingMailer(DeliveryOutcome.UNKNOWN),
    )
    unknown = await failing.create(issuer, replace(email, idempotency_key="email-2"))
    assert unknown.delivery_status == "unknown"


def test_private_account_tables_and_functions_keep_least_privilege(
    admin_conn: PgConnection,
) -> None:
    tables = (
        "account_invitations",
        "account_invitation_facts",
        "account_entitlements",
        "account_organization_creations",
    )
    for table in tables:
        assert admin_conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = %s::regclass",
            (f"request_engine.{table}",),
        ).fetchone() == (True, True)
        for role in ("request_engine_app", "request_platform_control", "request_engine_worker"):
            with pytest.raises(InsufficientPrivilege), admin_conn.transaction():
                admin_conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                admin_conn.execute(
                    sql.SQL("SELECT 1 FROM request_engine.{}").format(sql.Identifier(table))
                )
    runtime = {
        "request_auth.enroll_account_invitation(uuid,bytea,uuid,uuid,uuid,text,text)",
        "request_auth.read_account_entitlement(uuid,uuid)",
        "request_auth.create_self_service_organization("
        "uuid,uuid,uuid,text,text,uuid,uuid,uuid,text,text,text,text,text,text,uuid)",
    }
    control = {
        "request_platform.create_account_invitation("
        "uuid,bytea,text,text,text,integer,timestamp with time zone,text,text,text)",
        "request_platform.record_account_invitation_delivery(uuid,text)",
        "request_platform.revoke_account_invitation(uuid,bigint,text,text,text)",
    }
    for function in runtime | control | {"request_auth.lock_active_native_session(uuid,uuid,uuid)"}:
        for role, expected in (
            ("request_engine_app", function in runtime),
            ("request_platform_control", function in control),
            ("public", False),
        ):
            assert admin_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, function)
            ).fetchone() == (expected,), (role, function)
