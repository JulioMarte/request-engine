"""Supported global native-disable versus adoption under the topology gate.

Explicit fixture accounts/authority precede the race. The actual competing
commands use runtime roles, independent transactions and observed PostgreSQL
blocking. This does not claim black-box enrollment or production authentication.
"""

import asyncio
import hashlib
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.adapters.db.native_identity_disable_commands import (
    PostgresNativeIdentityDisableCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionConsentInvalidated,
    ControllerPolicyAdoptionForbidden,
    RequestControllerPolicyAdoption,
)
from request_engine.modules.tenancy.application.commands.native_identity_disable import (
    DisableNativeIdentityCommand,
)
from request_engine.platform.db.session import SessionFactory

from .test_controller_policy_adoption_apply_race import (
    adoption_platform_actor,
    adoption_wait_for_blocker,
)
from .test_controller_policy_adoption_lifecycle_races import (
    PgConnection,
    adoption_apply_uncommitted,
    adoption_assert_adoption_effects,
    adoption_second_controller,
    adoption_set_actor,
    adoption_world,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.concurrency,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("participant", ["controller", "approver"])
@pytest.mark.parametrize("order", ["disable-first", "apply-first"])
async def test_global_native_disable_and_adoption_serialize_in_both_orders(
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
    target_native = controller_native if participant == "controller" else approver_native
    authority = e2e_admin_conn.execute(
        "SELECT identity_authority_id FROM request_engine.native_identities WHERE id=%s",
        (target_native,),
    ).fetchone()
    assert authority is not None
    manager = await adoption_second_controller(
        e2e_admin_conn, e2e_session_factory, root, controller_native
    )
    native = build_native_auth_runtime(e2e_session_factory)
    identity = await native.service.enroll_password_identity(
        identity_authority_id=authority[0],
        login_handle=f"disable-operator-{uuid4().hex}@example.test",
        password="disable-operator-fixture-password-123",
    )
    operator = adoption_platform_actor(e2e_admin_conn, authority[0], identity.native_identity_id)
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','platform.identity.disable',false,'trust_bootstrap',%s)",
        (operator.principal_id, f"disable-operator:{uuid4().hex}"),
    )
    operator_revision = e2e_admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (operator.principal_id,),
    ).fetchone()
    assert operator_revision is not None
    operator = replace(
        operator,
        authority_revision=operator_revision[0],
        capabilities=operator.capabilities | {"platform.identity.disable"},
    )
    target_revision = e2e_admin_conn.execute(
        "SELECT revision FROM request_engine.native_identities WHERE id=%s", (target_native,)
    ).fetchone()
    assert target_revision is not None
    adoption = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await adoption.request_adoption(
        root,
        RequestControllerPolicyAdoption(
            expected_authority_revision=root.authority_revision,
            reason="Native-disable must not race an adoption past revoked reachability",
            idempotency_key=f"disable-consent:{uuid4().hex}",
        ),
    )
    task: asyncio.Task[Any] | None = None
    try:
        if order == "disable-first":
            adoption_set_actor(e2e_barrier_conn, operator)
            e2e_barrier_conn.execute("SET LOCAL ROLE request_platform_control")
            disabled = e2e_barrier_conn.execute(
                "SELECT * FROM request_platform.disable_native_identity(%s,%s,%s,%s,%s,%s)",
                (
                    target_native,
                    target_revision[0],
                    "operator_revocation",
                    f"case:{uuid4().hex}",
                    hashlib.sha256(uuid4().bytes).hexdigest(),
                    hashlib.sha256(uuid4().bytes).hexdigest(),
                ),
            ).fetchone()
            assert disabled is not None
            task = asyncio.create_task(
                adoption.apply_adoption(
                    approver,
                    ApplyControllerPolicyAdoption(
                        request_id=request.request_id,
                        expected_request_revision=request.request_revision,
                        idempotency_key=f"disable-apply:{uuid4().hex}",
                    ),
                )
            )
            await adoption_wait_for_blocker(
                e2e_admin_conn,
                "apply_controller_policy_adoption",
                e2e_barrier_conn.info.backend_pid,
            )
            e2e_barrier_conn.commit()
            with pytest.raises(
                ControllerPolicyAdoptionConsentInvalidated
                if participant == "controller"
                else ControllerPolicyAdoptionForbidden
            ):
                await asyncio.wait_for(task, timeout=15)
        else:
            adoption_apply_uncommitted(e2e_barrier_conn, approver, request)
            disable = PostgresNativeIdentityDisableCommands(platform_control_session_factory)
            task = asyncio.create_task(
                disable.disable_identity(
                    operator,
                    DisableNativeIdentityCommand(
                        native_identity_id=target_native,
                        expected_revision=target_revision[0],
                        reason_code="operator_revocation",
                        external_case_reference=f"case:{uuid4().hex}",
                        idempotency_key=f"apply-first-disable:{uuid4().hex}",
                    ),
                )
            )
            await adoption_wait_for_blocker(
                e2e_admin_conn, "disable_native_identity", e2e_barrier_conn.info.backend_pid
            )
            e2e_barrier_conn.commit()
            result = await asyncio.wait_for(task, timeout=15)
            assert result.native_identity_id == target_native
            assert result.revision_after == target_revision[0] + 1
            assert result.affected_tenant_count == int(participant == "controller")
    finally:
        e2e_barrier_conn.rollback()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert e2e_admin_conn.execute(
        "SELECT status,revision FROM request_engine.native_identities WHERE id=%s", (target_native,)
    ).fetchone() == ("disabled", target_revision[0] + 1)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id=%s AND status='active'",
        (target_native,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_disable_facts "
        "WHERE native_identity_id=%s AND actor_principal_id=%s",
        (target_native, operator.principal_id),
    ).fetchone() == (1,)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.identity_bindings WHERE id=%s",
        (
            root.identity_binding_id
            if participant == "controller"
            else approver.identity_binding_id,
        ),
    ).fetchone() == ("active",)  # Disable preserves bindings as historical authority links.
    with e2e_admin_conn.transaction():
        adoption_set_actor(e2e_admin_conn, manager)
        assert e2e_admin_conn.execute(
            "SELECT request_engine.principal_is_effective_tenant_controller(%s,%s)",
            (root.organization_id, manager.principal_id),
        ).fetchone() == (True,)
    adoption_assert_adoption_effects(
        e2e_admin_conn, request, root, set(root.capabilities), applied=order == "apply-first"
    )
