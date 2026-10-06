"""PostgreSQL proof that owner revocation wins over a waiting adoption apply."""

import asyncio
import hashlib
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
from request_engine.modules.tenancy.adapters.db.platform_owner_commands import (
    PostgresPlatformOwnerCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionForbidden,
    RequestControllerPolicyAdoption,
)
from request_engine.modules.tenancy.application.commands.platform_owner_lifecycle import (
    PlatformOwnerLifecycleAction,
    TransitionPlatformOwnerCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


def _scalar(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _new_platform_principal(
    conn: PgConnection, authority_id: UUID, native_id: UUID, capabilities: tuple[str, ...]
) -> tuple[UUID, UUID, int]:
    principal = _scalar(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"owner-revoke-race-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,'platform',%s,%s,'active')",
        (principal, authority_id, str(native_id)),
    )
    for capability in capabilities:
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,provenance_kind,"
            "provenance_reference) VALUES (%s,'platform','platform',%s,false,"
            "'trust_bootstrap',%s)",
            (principal, capability, f"owner-revoke-race:{uuid4().hex}"),
        )
    binding = _scalar(
        conn, "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s", (principal,)
    )
    revision = _scalar(
        conn, "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (principal,)
    )
    return principal, binding, int(revision)


async def _wait_for_blocker(observer: PgConnection, fragment: str, blocker_pid: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        rows = observer.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE %s",
            (f"%{fragment}%",),
        ).fetchall()
        if any(blocker_pid in blockers for _, blockers in rows):
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"PostgreSQL did not show {fragment!r} blocked by PID {blocker_pid}")


@pytest.mark.asyncio
@pytest.mark.parametrize("race_order", ["revocation-first", "apply-first"])
async def test_owner_revocation_wins_before_waiting_adoption_apply(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    race_order: str,
) -> None:
    """Lifecycle revocation and adoption apply serialize in either lock order."""
    authority_id = _scalar(
        e2e_admin_conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"owner-revocation-race-{uuid4().hex}",),
    )
    enrollment = build_native_auth_runtime(e2e_session_factory)
    root_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"revocation-root-{uuid4().hex}@example.test",
        password="owner-revocation-root-password-1",
    )
    approver_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"revocation-approver-{uuid4().hex}@example.test",
        password="owner-revocation-approver-password-2",
    )
    lifecycle_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"revocation-lifecycle-{uuid4().hex}@example.test",
        password="owner-revocation-lifecycle-password-3",
    )

    # Provision a legacy root through the canonical function, including a real
    # tenant-plane principal/binding and bootstrap capability provenance.
    provisioner = _scalar(
        e2e_admin_conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"revocation-provisioner-{uuid4().hex}",),
    )
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner, f"revocation-provisioner:{uuid4().hex}"),
    )
    provisioner_revision = _scalar(
        e2e_admin_conn,
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (provisioner,),
    )
    org_id, party_id, root_id = uuid4(), uuid4(), uuid4()
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner),),
    )
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)",
        (str(provisioner_revision),),
    )
    with e2e_admin_conn.transaction():
        e2e_admin_conn.execute("SET ROLE request_platform_control")
        try:
            e2e_admin_conn.execute(
                "SELECT request_platform.select_initial_controller_policy(%s)",
                ("tenant-controller-v1",),
            )
            e2e_admin_conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root(%s,%s,%s,"
                "%s,%s,%s,%s,%s)",
                (
                    org_id,
                    f"revocation-race-{org_id.hex}",
                    "Owner revocation race proof",
                    party_id,
                    root_id,
                    authority_id,
                    root_identity.native_identity_id,
                    f"revocation-root:{uuid4().hex}",
                ),
            )
        finally:
            e2e_admin_conn.execute("RESET ROLE")
    root_binding = _scalar(
        e2e_admin_conn,
        "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s",
        (root_id,),
    )
    root_revision = int(
        _scalar(
            e2e_admin_conn,
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
            (root_id,),
        )
    )
    root_caps = frozenset(
        str(row[0])
        for row in e2e_admin_conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active'",
            (org_id, root_id),
        ).fetchall()
    )
    tenant_actor = ActorContext(
        organization_id=org_id,
        principal_id=root_id,
        capabilities=root_caps,
        authority_revision=root_revision,
        identity_binding_id=root_binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=datetime.now(UTC),
    )

    approver_id, approver_binding, approver_revision = _new_platform_principal(
        e2e_admin_conn,
        authority_id,
        approver_identity.native_identity_id,
        (
            "platform.organization.adopt_initial_controller_policy",
            "platform.organization.read",
            "platform.owner.manage_lifecycle",
        ),
    )
    lifecycle_id, lifecycle_binding, lifecycle_revision = _new_platform_principal(
        e2e_admin_conn,
        authority_id,
        lifecycle_identity.native_identity_id,
        ("platform.owner.manage_lifecycle",),
    )
    now = datetime.now(UTC)
    approver_actor = PlatformActorContext(
        principal_id=approver_id,
        capabilities=frozenset(
            {
                "platform.organization.adopt_initial_controller_policy",
                "platform.organization.read",
                "platform.owner.manage_lifecycle",
            }
        ),
        authority_revision=approver_revision,
        identity_binding_id=approver_binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    lifecycle_actor = PlatformActorContext(
        principal_id=lifecycle_id,
        capabilities=frozenset({"platform.owner.manage_lifecycle"}),
        authority_revision=lifecycle_revision,
        identity_binding_id=lifecycle_binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=now,
    )
    adoption = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await adoption.request_adoption(
        tenant_actor,
        RequestControllerPolicyAdoption(
            expected_authority_revision=root_revision,
            reason="Approver lifecycle revocation must invalidate a waiting apply",
            idempotency_key=f"owner-revocation-request:{uuid4().hex}",
        ),
    )

    lifecycle_commands = PostgresPlatformOwnerCommands(
        platform_control_session_factory, native_authority_id=authority_id
    )
    revoked: tuple[Any, ...] | None = None
    apply_task: asyncio.Task[Any] | None = None
    lifecycle_task: asyncio.Task[Any] | None = None
    try:
        if race_order == "revocation-first":
            # Run the real lifecycle function and hold its committed revocation
            # pending; apply must wait, then reject the now-revoked approver.
            for key, value in (
                ("request_engine.authenticated_principal_id", str(lifecycle_id)),
                ("request_engine.authority_revision", str(lifecycle_revision)),
                ("request_engine.identity_binding_id", str(lifecycle_binding)),
                ("request_engine.authentication_method", "passkey"),
                ("request_engine.correlation_id", str(uuid4())),
            ):
                e2e_barrier_conn.execute("SELECT set_config(%s,%s,false)", (key, value))
            key_digest = hashlib.sha256(f"revoke-approver:{uuid4().hex}".encode()).hexdigest()
            intent_digest = hashlib.sha256(f"revoke-intent:{approver_id}".encode()).hexdigest()
            e2e_barrier_conn.execute("SET LOCAL ROLE request_platform_control")
            revoked = e2e_barrier_conn.execute(
                "SELECT * FROM request_platform.transition_native_platform_owner(%s,'revoke',%s,"
                "'owner_revocation',%s,%s,%s)",
                (
                    approver_id,
                    approver_revision,
                    f"case:{uuid4().hex}",
                    key_digest,
                    intent_digest,
                ),
            ).fetchone()
            assert revoked is not None
            blocker_pid = e2e_barrier_conn.info.backend_pid
            apply_task = asyncio.create_task(
                adoption.apply_adoption(
                    approver_actor,
                    ApplyControllerPolicyAdoption(
                        request_id=request.request_id,
                        expected_request_revision=request.request_revision,
                        idempotency_key=f"revoked-approver-apply:{uuid4().hex}",
                    ),
                )
            )
            await _wait_for_blocker(e2e_admin_conn, "apply_controller_policy_adoption", blocker_pid)
            e2e_barrier_conn.commit()
            with pytest.raises(ControllerPolicyAdoptionForbidden):
                await asyncio.wait_for(apply_task, timeout=15)
        else:
            # Apply executes through its real SQL command and remains uncommitted.
            # The application lifecycle command then blocks on the approver row.
            for key, value in (
                ("request_engine.authenticated_principal_id", str(approver_id)),
                ("request_engine.authority_revision", str(approver_revision)),
                ("request_engine.identity_binding_id", str(approver_binding)),
                ("request_engine.correlation_id", str(uuid4())),
            ):
                e2e_barrier_conn.execute("SELECT set_config(%s,%s,false)", (key, value))
            e2e_barrier_conn.execute("SET LOCAL ROLE request_platform_control")
            applied = e2e_barrier_conn.execute(
                "SELECT * FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
                (
                    request.request_id,
                    request.request_revision,
                    hashlib.sha256(f"apply-first:{uuid4().hex}".encode()).hexdigest(),
                    hashlib.sha256(f"apply-first-intent:{request.request_id}".encode()).hexdigest(),
                ),
            ).fetchone()
            assert applied is not None
            blocker_pid = e2e_barrier_conn.info.backend_pid
            lifecycle_task = asyncio.create_task(
                lifecycle_commands.transition_owner(
                    lifecycle_actor,
                    TransitionPlatformOwnerCommand(
                        principal_id=approver_id,
                        action=PlatformOwnerLifecycleAction.REVOKE,
                        expected_revision=approver_revision,
                        reason_code="owner_revocation",
                        idempotency_key=f"apply-first-revoke:{uuid4().hex}",
                        external_case_reference=f"case:{uuid4().hex}",
                    ),
                )
            )
            await _wait_for_blocker(e2e_admin_conn, "transition_native_platform_owner", blocker_pid)
            e2e_barrier_conn.commit()
            revoked_result = await asyncio.wait_for(lifecycle_task, timeout=15)
            revoked = (
                revoked_result.fact_id,
                revoked_result.principal_id,
                revoked_result.action.value,
                revoked_result.authority_revision,
                revoked_result.binding_id,
                revoked_result.binding_status,
            )
    finally:
        if not e2e_barrier_conn.autocommit:
            e2e_barrier_conn.rollback()
        for key in (
            "request_engine.authenticated_principal_id",
            "request_engine.authority_revision",
            "request_engine.identity_binding_id",
            "request_engine.authentication_method",
            "request_engine.correlation_id",
        ):
            e2e_barrier_conn.execute("SELECT set_config(%s,'',false)", (key,))
        e2e_barrier_conn.commit()
        for task in (apply_task, lifecycle_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (apply_task, lifecycle_task) if task is not None),
            return_exceptions=True,
        )

    assert revoked is not None
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id=%s", (revoked[4],)
    ).fetchone() == ("revoked",)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND status='active'",
        (approver_id,),
    ).fetchone() == (0,)
    if race_order == "revocation-first":
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.controller_policy_adoption_requests WHERE id=%s",
            (request.request_id,),
        ).fetchone() == ("pending",)
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request.request_id,),
        ).fetchone() == (0,)
    else:
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.controller_policy_adoption_requests WHERE id=%s",
            (request.request_id,),
        ).fetchone() == ("applied",)
        fact = e2e_admin_conn.execute(
            "SELECT added_capabilities FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request.request_id,),
        ).fetchone()
        assert fact is not None
        actual_capabilities = {
            str(row[0])
            for row in e2e_admin_conn.execute(
                "SELECT capability_key FROM request_engine.principal_authority_grants "
                "WHERE organization_id=%s AND principal_id=%s "
                "AND provenance_reference=%s AND status='active'",
                (org_id, root_id, f"adoption:{request.request_id}"),
            ).fetchall()
        }
        assert actual_capabilities == set(fact[0])
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request.request_id,),
        ).fetchone() == (1,)
