import asyncio
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from platform_provisioning_support import platform_grant as _platform_grant
from platform_provisioning_support import platform_principal as _platform_principal
from platform_provisioning_support import principal_revision as _revision
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.native_platform_provisioning_commands import (
    PostgresNativePlatformProvisioningCommands,
)
from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NativePlatformProvisionerResult,
    NativePlatformProvisioningConflict,
    NativePlatformProvisioningForbidden,
    NativePlatformProvisioningInvalid,
    NativePlatformProvisioningRevisionConflict,
    ProvisionNativePlatformProvisionerCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.platform_context import PlatformActorContext

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]
PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_native_provisioner_is_atomic_replay_safe_and_never_regrants(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    creator = _platform_principal(admin_conn)
    for capability in ("platform.tenant_provisioner.provision", "organization.provision"):
        _platform_grant(admin_conn, principal_id=creator, capability=capability, delegable=True)
    actor = PlatformActorContext(
        principal_id=creator,
        authority_revision=_revision(admin_conn, creator),
        capabilities=frozenset({"platform.tenant_provisioner.provision", "organization.provision"}),
    )
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"native-provisioner-{uuid4().hex}"),
    )
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="tenant-provisioner@example.test",
        password="native provisioner proof password",
    )
    command = ProvisionNativePlatformProvisionerCommand(
        identity_authority_id=authority_id,
        native_identity_id=enrollment.native_identity_id,
        provenance_reference="deployment:provisioner-v1",
        idempotency_key="native-provisioner-1",
    )
    commands = PostgresNativePlatformProvisioningCommands(platform_control_session_factory)
    # Force both independent command transactions to contend on the creator,
    # then release them only after PostgreSQL reports both lock waits.
    locker = PgConnection.connect(pg_conninfo)
    locker.execute("SELECT id FROM request_engine.principals WHERE id=%s FOR UPDATE", (creator,))
    tasks = [
        asyncio.create_task(commands.provision_native_platform_provisioner(actor, command))
        for _ in range(2)
    ]
    try:
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            waiting = admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND usename LIKE 're_platform_control_%%' AND wait_event_type='Lock'"
            ).fetchone()
            if waiting == (2,):
                break
            assert not any(task.done() for task in tasks), "command bypassed the creator lock"
            assert asyncio.get_running_loop().time() < deadline, "both transactions must contend"
            await asyncio.sleep(0.01)
    finally:
        locker.rollback()
        locker.close()
        outcomes = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=10
        )
    result = outcomes[0]
    assert isinstance(result, NativePlatformProvisionerResult), outcomes
    assert outcomes[1] == result
    assert await commands.provision_native_platform_provisioner(actor, command) == result
    assert admin_conn.execute(
        "SELECT principal_id, principal_plane, organization_id, identity_authority_id, "
        "subject_id, status FROM request_engine.identity_bindings WHERE id = %s",
        (result.binding_id,),
    ).fetchone() == (
        result.principal_id,
        "platform",
        None,
        authority_id,
        str(enrollment.native_identity_id),
        "active",
    )
    assert admin_conn.execute(
        "SELECT capability_key, delegable, granted_by_principal_id, provenance_reference "
        "FROM request_engine.principal_authority_grants WHERE principal_id = %s",
        (result.principal_id,),
    ).fetchall() == [("organization.provision", False, creator, "deployment:provisioner-v1")]

    for conflicting in (
        replace(command, provenance_reference="different-intent"),
        replace(command, native_identity_id=uuid4()),
        replace(command, idempotency_key="different-key-same-identity"),
    ):
        with pytest.raises(NativePlatformProvisioningConflict):
            await commands.provision_native_platform_provisioner(actor, conflicting)
    with pytest.raises(NativePlatformProvisioningInvalid):
        await commands.provision_native_platform_provisioner(
            actor, replace(command, native_identity_id=uuid4(), idempotency_key="missing-identity")
        )
    assert admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (2,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (1,)
    assert admin_conn.execute("SELECT count(*) FROM request_engine.organizations").fetchone() == (
        0,
    )

    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='organization.provision'",
        (creator, result.principal_id),
    )
    assert await commands.provision_native_platform_provisioner(actor, command) == result
    assert admin_conn.execute(
        "SELECT status FROM request_engine.principal_authority_grants WHERE principal_id=%s",
        (result.principal_id,),
    ).fetchall() == [("revoked",)]
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='organization.provision'",
        (creator, creator),
    )
    with pytest.raises(NativePlatformProvisioningRevisionConflict):
        await commands.provision_native_platform_provisioner(actor, command)
    with pytest.raises(NativePlatformProvisioningForbidden):
        await commands.provision_native_platform_provisioner(
            replace(actor, authority_revision=_revision(admin_conn, creator)), command
        )
