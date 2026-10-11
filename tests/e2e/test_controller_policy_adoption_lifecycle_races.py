"""Owner-command PostgreSQL proof of adoption versus participant lifecycle.

This is a database/application proof with explicit trusted fixture identities,
not a black-box enrollment or passkey-login journey. Each winner executes its
supported owner function as the runtime role and holds its transaction open;
pg_blocking_pids proves that the independent loser actually waits for commit.
"""

import asyncio
import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.adapters.db.identity_binding_commands import (
    PostgresIdentityBindingCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionConsentInvalidated,
    ControllerPolicyAdoptionForbidden,
    RequestControllerPolicyAdoption,
)
from request_engine.modules.tenancy.application.commands.identity_binding import (
    IdentityBindingTargetStatus,
    TransitionIdentityBindingCommand,
)
from request_engine.modules.tenancy.application.commands.staff_membership import (
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
)
from request_engine.platform.db.recovery_code_store import PostgresRecoveryCodeStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import hash_password
from request_engine.platform.security.recovery_codes import (
    NativeRecoveryCodeService,
    recovery_code_digest,
)

from .test_controller_policy_adoption_apply_race import (
    adoption_create_authority,
    adoption_platform_actor,
    adoption_provision_root,
    adoption_root_actor,
    adoption_wait_for_blocker,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.concurrency,
]


def adoption_set_actor(conn: PgConnection, actor: Any) -> None:
    for key, value in (
        ("authenticated_principal_id", str(actor.principal_id)),
        ("authority_revision", str(actor.authority_revision)),
        ("identity_binding_id", str(actor.identity_binding_id)),
        ("correlation_id", str(uuid4())),
        ("principal_kind", "human"),
        ("authentication_method", "passkey"),
    ):
        conn.execute("SELECT set_config(%s,%s,true)", (f"request_engine.{key}", value))
    if hasattr(actor, "organization_id"):
        conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true)",
            (str(actor.organization_id),),
        )


def adoption_apply_uncommitted(conn: PgConnection, actor: Any, request: Any) -> None:
    adoption_set_actor(conn, actor)
    conn.execute("SET LOCAL ROLE request_platform_control")
    row = conn.execute(
        "SELECT * FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
        (
            request.request_id,
            request.request_revision,
            hashlib.sha256(uuid4().bytes).hexdigest(),
            hashlib.sha256(uuid4().bytes).hexdigest(),
        ),
    ).fetchone()
    assert row is not None


def adoption_assert_adoption_effects(
    conn: PgConnection,
    request: Any,
    root: Any,
    before: set[str],
    *,
    applied: bool,
    lifecycle_revision_delta: int = 0,
) -> None:
    assert conn.execute(
        "SELECT status,revision FROM request_engine.controller_policy_adoption_requests "
        "WHERE id=%s",
        (request.request_id,),
    ).fetchone() == ("applied" if applied else "pending", request.request_revision + int(applied))
    facts = conn.execute(
        "SELECT added_capabilities,authority_revision_before,authority_revision_after "
        "FROM request_engine.controller_policy_adoption_facts WHERE request_id=%s",
        (request.request_id,),
    ).fetchall()
    grants = {
        row[0]
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active' "
            "AND provenance_reference=%s",
            (root.organization_id, root.principal_id, f"adoption:{request.request_id}"),
        ).fetchall()
    }
    all_grants = {
        row[0]
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active'",
            (root.organization_id, root.principal_id),
        ).fetchall()
    }
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (root.principal_id,)
    ).fetchone()
    if applied:
        assert len(facts) == 1
        assert grants == set(facts[0][0])
        assert grants  # A vacuous no-op must not count as a successful adoption.
        assert all_grants == before | grants
        assert facts[0][1] == root.authority_revision
        assert facts[0][2] > root.authority_revision
        assert revision == (facts[0][2] + lifecycle_revision_delta,)
    else:
        assert facts == []
        assert grants == set()
        assert all_grants == before
        assert revision == (root.authority_revision + lifecycle_revision_delta,)


async def adoption_world(
    conn: PgConnection, sessions: SessionFactory
) -> tuple[Any, Any, UUID, UUID]:
    authority = adoption_create_authority(conn)
    native = build_native_auth_runtime(sessions)
    identities: list[UUID] = []
    for prefix in ("controller", "approver"):
        identity = await native.service.enroll_password_identity(
            identity_authority_id=authority,
            login_handle=f"lifecycle-{prefix}-{uuid4().hex}@example.test",
            password="lifecycle-fixture-password-123",
        )
        identities.append(identity.native_identity_id)
    org, principal, binding = adoption_provision_root(conn, authority, identities[0])
    return (
        adoption_root_actor(conn, org, principal, binding),
        adoption_platform_actor(conn, authority, identities[1]),
        identities[0],
        identities[1],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("participant", ["controller", "approver"])
@pytest.mark.parametrize("order", ["recovery-first", "apply-first"])
async def test_native_recovery_and_adoption_serialize_in_both_orders(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    participant: str,
    order: str,
) -> None:
    root, approver, controller_native, approver_native = await adoption_world(
        e2e_admin_conn, e2e_session_factory
    )
    recovery_native = controller_native if participant == "controller" else approver_native
    recovery = NativeRecoveryCodeService(store=PostgresRecoveryCodeStore(e2e_session_factory))
    codes = await recovery.issue_for_identity(native_identity_id=recovery_native)
    commands = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await commands.request_adoption(
        root,
        RequestControllerPolicyAdoption(
            expected_authority_revision=root.authority_revision,
            reason="Recovery and apply must use the same durable identity posture",
            idempotency_key=f"lifecycle-consent:{uuid4().hex}",
        ),
    )
    before = set(root.capabilities)
    task: asyncio.Task[Any] | None = None
    try:
        if order == "recovery-first":
            e2e_barrier_conn.execute("SET LOCAL ROLE request_engine_app")
            recovered = e2e_barrier_conn.execute(
                "SELECT request_auth.consume_recovery_code_and_rotate_password(%s,%s,%s)",
                (
                    recovery_code_digest(codes[0]),
                    uuid4(),
                    hash_password("new-recovery-password-123"),
                ),
            ).fetchone()
            assert recovered == (recovery_native,)
            task = asyncio.create_task(
                commands.apply_adoption(
                    approver,
                    ApplyControllerPolicyAdoption(
                        request_id=request.request_id,
                        expected_request_revision=request.request_revision,
                        idempotency_key=f"lifecycle-apply:{uuid4().hex}",
                    ),
                )
            )
            await adoption_wait_for_blocker(
                e2e_admin_conn,
                "apply_controller_policy_adoption",
                e2e_barrier_conn.info.backend_pid,
            )
            e2e_barrier_conn.commit()
            error = (
                ControllerPolicyAdoptionConsentInvalidated
                if participant == "controller"
                else ControllerPolicyAdoptionForbidden
            )
            with pytest.raises(error):
                await asyncio.wait_for(task, timeout=15)
        else:
            adoption_apply_uncommitted(e2e_barrier_conn, approver, request)
            task = asyncio.create_task(
                recovery.recover_password(code=codes[0], new_password="new-recovery-password-123")
            )
            await adoption_wait_for_blocker(
                e2e_admin_conn,
                "consume_recovery_code_and_rotate_password",
                e2e_barrier_conn.info.backend_pid,
            )
            e2e_barrier_conn.commit()
            assert await asyncio.wait_for(task, timeout=15) == recovery_native
    finally:
        e2e_barrier_conn.rollback()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert e2e_admin_conn.execute(
        "SELECT state,recovery_epoch FROM request_engine.native_identity_recovery_state "
        "WHERE native_identity_id=%s",
        (recovery_native,),
    ).fetchone() == ("recovery_restricted", 1)
    assert e2e_admin_conn.execute(
        "SELECT used_at IS NOT NULL FROM request_engine.recovery_codes WHERE code_digest=%s",
        (recovery_code_digest(codes[0]),),
    ).fetchone() == (True,)
    adoption_assert_adoption_effects(
        e2e_admin_conn, request, root, before, applied=order == "apply-first"
    )


async def adoption_second_controller(
    conn: PgConnection, sessions: SessionFactory, root: Any, controller_native: UUID
) -> Any:
    authority = conn.execute(
        "SELECT identity_authority_id FROM request_engine.native_identities WHERE id=%s",
        (controller_native,),
    ).fetchone()
    assert authority is not None
    native = build_native_auth_runtime(sessions)
    second = await native.service.enroll_password_identity(
        identity_authority_id=authority[0],
        login_handle=f"lifecycle-manager-{uuid4().hex}@example.test",
        password="lifecycle-fixture-password-123",
    )
    # Fixture a pre-existing second effective controller. Without one the supported
    # suspension command must reject loss of the last controller. No adoption
    # request, adoption fact, resulting delta or recovery state is seeded here.
    manager_id, manager_binding = uuid4(), uuid4()
    anchor = conn.execute(
        "SELECT organization_party_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (root.organization_id,),
    ).fetchone()
    assert anchor is not None
    conn.execute(
        "INSERT INTO request_engine.principals(id,organization_id,principal_plane,principal_kind,"
        "external_subject) VALUES (%s,%s,'tenant','human',%s)",
        (manager_id, root.organization_id, f"native:{second.native_identity_id}"),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(id,organization_id,principal_id,"
        "principal_plane,identity_authority_id,subject_id,status) "
        "VALUES (%s,%s,%s,'tenant',%s,%s,'active')",
        (
            manager_binding,
            root.organization_id,
            manager_id,
            authority[0],
            str(second.native_identity_id),
        ),
    )
    conn.execute(
        "INSERT INTO request_engine.staff_memberships(id,organization_id,principal_id,"
        "identity_binding_id,authority_anchor_party_id,status,established_by_principal_id,"
        "provenance_kind,provenance_reference,activated_at) "
        "VALUES (%s,%s,%s,%s,%s,'active',%s,'staff_invitation',%s,clock_timestamp())",
        (
            uuid4(),
            root.organization_id,
            manager_id,
            manager_binding,
            anchor[0],
            root.principal_id,
            f"pre-existing-manager:{uuid4().hex}",
        ),
    )
    for capability in ("identity.bind", "staff.manage_authority", "staff.manage_membership"):
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(organization_id,principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,granted_by_principal_id,"
            "provenance_kind,provenance_reference) "
            "VALUES (%s,%s,'tenant','tenant_control',%s,false,%s,'provisioning',%s)",
            (
                root.organization_id,
                manager_id,
                capability,
                root.principal_id,
                f"pre-existing-manager:{uuid4().hex}",
            ),
        )
    return adoption_root_actor(conn, root.organization_id, manager_id, manager_binding)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["suspension-first", "apply-first"])
@pytest.mark.parametrize("surface", ["binding", "membership"])
async def test_controller_suspension_and_adoption_serialize_in_both_orders(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    order: str,
    surface: str,
) -> None:
    root, approver, controller_native, _ = await adoption_world(e2e_admin_conn, e2e_session_factory)
    manager = await adoption_second_controller(
        e2e_admin_conn, e2e_session_factory, root, controller_native
    )
    commands = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await commands.request_adoption(
        root,
        RequestControllerPolicyAdoption(
            expected_authority_revision=root.authority_revision,
            reason="Suspending the original controller must block unapplied consent",
            idempotency_key=f"suspension-consent:{uuid4().hex}",
        ),
    )
    binding_revision = e2e_admin_conn.execute(
        "SELECT revision FROM request_engine.identity_bindings WHERE id=%s",
        (root.identity_binding_id,),
    ).fetchone()
    assert binding_revision is not None
    membership = e2e_admin_conn.execute(
        "SELECT id,revision FROM request_engine.staff_memberships "
        "WHERE organization_id=%s AND principal_id=%s AND status='active'",
        (root.organization_id, root.principal_id),
    ).fetchone()
    assert membership is not None
    task: asyncio.Task[Any] | None = None
    try:
        if order == "suspension-first":
            adoption_set_actor(e2e_barrier_conn, manager)
            e2e_barrier_conn.execute("SET LOCAL ROLE request_engine_app")
            if surface == "binding":
                assert e2e_barrier_conn.execute(
                    "SELECT request_engine.transition_identity_binding(%s,%s,'suspended',%s)",
                    (root.identity_binding_id, binding_revision[0], f"suspend:{uuid4().hex}"),
                ).fetchone() == (binding_revision[0] + 1,)
            else:
                assert e2e_barrier_conn.execute(
                    "SELECT request_engine.transition_staff_membership(%s,%s,'suspended',%s)",
                    (membership[0], membership[1], f"suspend:{uuid4().hex}"),
                ).fetchone() == (membership[1] + 1,)
            task = asyncio.create_task(
                commands.apply_adoption(
                    approver,
                    ApplyControllerPolicyAdoption(
                        request_id=request.request_id,
                        expected_request_revision=request.request_revision,
                        idempotency_key=f"suspension-apply:{uuid4().hex}",
                    ),
                )
            )
            await adoption_wait_for_blocker(
                e2e_admin_conn,
                "apply_controller_policy_adoption",
                e2e_barrier_conn.info.backend_pid,
            )
            e2e_barrier_conn.commit()
            with pytest.raises(ControllerPolicyAdoptionForbidden):
                await asyncio.wait_for(task, timeout=15)
        else:
            adoption_apply_uncommitted(e2e_barrier_conn, approver, request)
            if surface == "binding":
                binding_commands = PostgresIdentityBindingCommands(e2e_session_factory)
                task = asyncio.create_task(
                    binding_commands.transition_identity_binding(
                        manager,
                        TransitionIdentityBindingCommand(
                            binding_id=root.identity_binding_id,
                            expected_revision=binding_revision[0],
                            target_status=IdentityBindingTargetStatus.SUSPENDED,
                            provenance_reference=f"suspend-controller:{uuid4().hex}",
                            idempotency_key=f"apply-first-suspend:{uuid4().hex}",
                        ),
                    )
                )
            else:
                staff_commands = PostgresStaffMembershipCommands(e2e_session_factory)
                task = asyncio.create_task(
                    staff_commands.transition_staff_membership(
                        manager,
                        TransitionStaffMembershipCommand(
                            membership_id=membership[0],
                            expected_revision=membership[1],
                            target_status=StaffMembershipTargetStatus.SUSPENDED,
                            provenance_reference=f"suspend-controller:{uuid4().hex}",
                            idempotency_key=f"apply-first-suspend:{uuid4().hex}",
                        ),
                    )
                )
            await adoption_wait_for_blocker(
                e2e_admin_conn,
                "transition_identity_binding"
                if surface == "binding"
                else "lock_staff_command_authority",
                e2e_barrier_conn.info.backend_pid,
            )
            e2e_barrier_conn.commit()
            assert (
                await asyncio.wait_for(task, timeout=15)
                == (binding_revision[0] if surface == "binding" else membership[1]) + 1
            )
    finally:
        e2e_barrier_conn.rollback()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert e2e_admin_conn.execute(
        "SELECT status,revision FROM request_engine.identity_bindings WHERE id=%s",
        (root.identity_binding_id,),
    ).fetchone() == ("suspended", binding_revision[0] + 1)
    assert e2e_admin_conn.execute(
        "SELECT status,revision FROM request_engine.staff_memberships WHERE id=%s",
        (membership[0],),
    ).fetchone() == (
        "active" if surface == "binding" else "suspended",
        membership[1] + int(surface == "membership"),
    )
    assert e2e_admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id=%s", (root.principal_id,)
    ).fetchone() == (surface == "binding",)
    with e2e_admin_conn.transaction():
        adoption_set_actor(e2e_admin_conn, manager)
        assert e2e_admin_conn.execute(
            "SELECT request_engine.principal_is_effective_tenant_controller(%s,%s)",
            (root.organization_id, manager.principal_id),
        ).fetchone() == (True,)
    adoption_assert_adoption_effects(
        e2e_admin_conn,
        request,
        root,
        set(root.capabilities),
        applied=order == "apply-first",
        lifecycle_revision_delta=1 if surface == "binding" else 2,
    )
