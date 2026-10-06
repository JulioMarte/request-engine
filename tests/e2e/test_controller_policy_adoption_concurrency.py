"""Deterministic PostgreSQL lock-order proof for policy adoption withdrawal."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionConflict,
    RequestControllerPolicyAdoption,
    WithdrawControllerPolicyAdoption,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _create_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"adoption-race-{uuid4().hex}",),
    )


def _provision_legacy_root(
    conn: PgConnection, authority_id: UUID, native_id: UUID
) -> tuple[UUID, UUID, UUID]:
    provisioner = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"adoption-race-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner, f"adoption-race-provisioner:{uuid4().hex}"),
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (provisioner,)
    ).fetchone()
    assert revision_row is not None
    revision = int(revision_row[0])
    organization_id, party_id, root_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)", (str(revision),)
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute(
                "SELECT request_platform.select_initial_controller_policy(%s)",
                ("tenant-controller-v1",),
            )
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"adoption-race-{organization_id.hex}",
                    "Adoption concurrency proof",
                    party_id,
                    root_id,
                    authority_id,
                    native_id,
                    f"adoption-race-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    binding_id = _uuid_row(
        conn,
        "SELECT controller_binding_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (organization_id,),
    )
    return organization_id, root_id, binding_id


def _platform_owner(
    conn: PgConnection, authority_id: UUID, native_id: UUID
) -> tuple[UUID, UUID, int]:
    principal = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"adoption-race-owner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,'platform',%s,%s,'active')",
        (principal, authority_id, str(native_id)),
    )
    for capability in (
        "platform.organization.adopt_initial_controller_policy",
        "platform.organization.read",
    ):
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,provenance_kind,"
            "provenance_reference) VALUES (%s,'platform','platform',%s,false,"
            "'trust_bootstrap',%s)",
            (principal, capability, f"adoption-race-owner:{uuid4().hex}"),
        )
    binding_id = _uuid_row(
        conn, "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s", (principal,)
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (principal,)
    ).fetchone()
    assert revision_row is not None
    revision = int(revision_row[0])
    return principal, binding_id, int(revision)


def _actor_pair(
    conn: PgConnection,
    organization_id: UUID,
    root_id: UUID,
    root_binding: UUID,
    platform_id: UUID,
    platform_binding: UUID,
    platform_revision: int,
) -> tuple[ActorContext, PlatformActorContext]:
    root_revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (root_id,)
    ).fetchone()
    assert root_revision_row is not None
    root_revision = int(root_revision_row[0])
    root_caps = frozenset(
        str(row[0])
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active'",
            (organization_id, root_id),
        ).fetchall()
    )
    now = datetime.now(UTC)
    tenant = ActorContext(
        organization_id=organization_id,
        principal_id=root_id,
        capabilities=root_caps,
        authority_revision=root_revision,
        identity_binding_id=root_binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    platform = PlatformActorContext(
        principal_id=platform_id,
        capabilities=frozenset(
            {"platform.organization.adopt_initial_controller_policy", "platform.organization.read"}
        ),
        authority_revision=platform_revision,
        identity_binding_id=platform_binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    return tenant, platform


async def _wait_for_blocker(
    observer: PgConnection,
    query_fragment: str,
    blocker_pid: int,
    *,
    deadline_seconds: float = 15.0,
) -> int:
    """Wait for PostgreSQL to report the specific backend lock dependency."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        rows = observer.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE %s",
            (f"%{query_fragment}%",),
        ).fetchall()
        for pid, blockers in rows:
            if blocker_pid in blockers:
                return int(pid)
        await asyncio.sleep(0.025)
    raise AssertionError(
        f"PostgreSQL did not report {query_fragment!r} blocked by backend {blocker_pid}"
    )


@pytest.mark.asyncio
async def test_apply_waits_for_withdrawal_then_fails_closed(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    """Withdrawal owns tenant authority locks before apply can inspect request state."""
    authority_id = _create_authority(e2e_admin_conn)
    enrollment = build_native_auth_runtime(e2e_session_factory)
    root_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"adoption-race-root-{uuid4().hex}@example.test",
        password="adoption-race-root-password-1",
    )
    platform_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"adoption-race-owner-{uuid4().hex}@example.test",
        password="adoption-race-owner-password-2",
    )
    organization_id, root_id, root_binding_id = _provision_legacy_root(
        e2e_admin_conn,
        authority_id,
        root_identity.native_identity_id,
    )
    platform_id, platform_binding_id, platform_revision = _platform_owner(
        e2e_admin_conn, authority_id, platform_identity.native_identity_id
    )
    tenant_actor, platform_actor = _actor_pair(
        e2e_admin_conn,
        organization_id,
        root_id,
        root_binding_id,
        platform_id,
        platform_binding_id,
        platform_revision,
    )
    assert tenant_actor.authority_revision is not None
    commands = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await commands.request_adoption(
        tenant_actor,
        RequestControllerPolicyAdoption(
            expected_authority_revision=tenant_actor.authority_revision,
            reason="Withdraw if apply has not acquired authority first",
            idempotency_key=f"request:{uuid4().hex}",
        ),
    )

    # The independent holder deliberately blocks withdrawal only after its
    # canonical tenant-root/membership locks have been acquired. Apply must then
    # wait behind withdrawal, not overtake it and commit an adoption.
    e2e_barrier_conn.execute(
        "SELECT id FROM request_engine.controller_policy_adoption_requests WHERE id=%s FOR UPDATE",
        (request.request_id,),
    ).fetchone()
    holder_pid = e2e_barrier_conn.info.backend_pid
    withdraw_task = asyncio.create_task(
        commands.withdraw_adoption(
            tenant_actor,
            WithdrawControllerPolicyAdoption(
                request_id=request.request_id,
                expected_request_revision=request.request_revision,
                idempotency_key=f"withdraw:{uuid4().hex}",
            ),
        )
    )
    apply_task: asyncio.Task[object] | None = None
    try:
        withdrawal_pid = await _wait_for_blocker(
            e2e_admin_conn,
            "withdraw_controller_policy_adoption",
            holder_pid,
        )
        apply_task = asyncio.create_task(
            commands.apply_adoption(
                platform_actor,
                ApplyControllerPolicyAdoption(
                    request_id=request.request_id,
                    expected_request_revision=request.request_revision,
                    idempotency_key=f"apply:{uuid4().hex}",
                ),
            )
        )
        await _wait_for_blocker(
            e2e_admin_conn,
            "apply_controller_policy_adoption",
            withdrawal_pid,
        )

        e2e_barrier_conn.commit()
        withdrawn = await asyncio.wait_for(withdraw_task, timeout=15)
        assert withdrawn[1] == "withdrawn"
        with pytest.raises(ControllerPolicyAdoptionConflict):
            await asyncio.wait_for(apply_task, timeout=15)
    finally:
        if not e2e_barrier_conn.autocommit:
            e2e_barrier_conn.rollback()
        for task in (withdraw_task, apply_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(withdraw_task, return_exceptions=True)
        if apply_task is not None:
            await asyncio.gather(apply_task, return_exceptions=True)

    state = e2e_admin_conn.execute(
        "SELECT status FROM request_engine.controller_policy_adoption_requests WHERE id=%s",
        (request.request_id,),
    ).fetchone()
    assert state == ("withdrawn",)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.controller_policy_adoption_facts WHERE request_id=%s",
        (request.request_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE organization_id=%s AND principal_id=%s AND provenance_reference=%s",
        (organization_id, root_id, f"adoption:{request.request_id}"),
    ).fetchone() == (0,)
