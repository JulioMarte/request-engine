"""Frozen initial authority is private configuration, never a runtime wildcard."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from platform_provisioning_support import platform_grant, platform_principal, principal_revision
from psycopg import Connection, Error

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.native_platform_provisioning_commands import (
    PostgresNativePlatformProvisioningCommands,
)
from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NativeOrganizationResult,
    ProvisionNativeOrganizationCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.platform_context import PlatformActorContext

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


def test_policy_manifest_matches_explicit_reviewed_authority(admin_conn: Connection[Any]) -> None:
    row = admin_conn.execute(
        "SELECT revision, grants FROM request_engine.initial_controller_policies "
        "WHERE policy_key='tenant-controller-v1'"
    ).fetchone()
    assert row is not None and row[0] == 1
    # Independent oracle: deliberately not derived from migration/runtime helpers.
    expected = {
        "tenant_control": {
            "agent.policy.read",
            "agent.manage_policy",
            "integration.provision",
            "integration.read",
            "integration.manage_authority",
            "integration.suspend",
            "delegation.create",
            "delegation.revoke",
        },
        "operational": {
            "organization.bootstrap",
            "catalog.manage",
            "booking.manage_supply",
            "discovery.manage",
            "onboarding.read",
            "business.get_info",
            "catalog.search_offerings",
            "catalog.get_offering_details",
            "parties.register",
            "parties.lookup",
            "appointments.find_slots",
            "appointments.book",
            "appointments.read",
            "appointments.cancel",
            "appointments.reschedule",
            "appointments.subject_override",
            "appointments.day_board",
        },
    }
    grants = row[1]
    assert len(grants) == 25
    assert {(g["authority_plane"], g["capability_key"], g["delegable"]) for g in grants} == {
        (plane, key, True) for plane, keys in expected.items() for key in keys
    }
    for grant in grants:
        definition = capability_definition(grant["capability_key"])
        assert definition is not None
        assert definition.authority_plane.value == grant["authority_plane"]


@pytest.mark.parametrize("role", ["request_engine_app", "request_engine_worker"])
def test_policy_catalog_is_not_runtime_table(admin_conn: Connection[Any], role: str) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert admin_conn.execute(
            "SELECT has_table_privilege(%s, 'request_engine.initial_controller_policies', %s)",
            (role, privilege),
        ).fetchone() == (False,)


@pytest.mark.parametrize("policy", ["tenant-controller-v1", "tenant-controller-v2"])
def test_policy_is_immutable_and_unknown_selection_fails(
    admin_conn: Connection[Any], policy: str
) -> None:
    with pytest.raises(Error) as immutable_update, admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.initial_controller_policies SET revision=2 WHERE policy_key=%s",
            (policy,),
        )
    assert immutable_update.value.sqlstate == "55000"
    with pytest.raises(Error) as immutable_delete, admin_conn.transaction():
        admin_conn.execute(
            "DELETE FROM request_engine.initial_controller_policies WHERE policy_key=%s",
            (policy,),
        )
    assert immutable_delete.value.sqlstate == "55000"
    with pytest.raises(Error) as rejected, admin_conn.transaction():
        admin_conn.execute("SET LOCAL ROLE request_platform_control")
        admin_conn.execute("SELECT request_platform.select_initial_controller_policy('future')")
    assert rejected.value.sqlstate == "22023"
    with admin_conn.transaction():
        admin_conn.execute("SET LOCAL ROLE request_platform_control")
        admin_conn.execute(
            "SELECT request_platform.select_initial_controller_policy('tenant-controller-v1')"
        )
        assert admin_conn.execute(
            "SELECT current_setting('request_engine.initial_controller_policy', true)"
        ).fetchone() == ("tenant-controller-v1",)
    assert admin_conn.execute(
        "SELECT NULLIF(current_setting('request_engine.initial_controller_policy', true), '')"
    ).fetchone() == (None,)


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_competing_creations_materialize_exactly_one_initial_policy(
    admin_conn: Connection[Any],
    pg_conninfo: str,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    creator = platform_principal(admin_conn)
    platform_grant(
        admin_conn, principal_id=creator, capability="organization.provision", delegable=False
    )
    actor = PlatformActorContext(
        principal_id=creator,
        authority_revision=principal_revision(admin_conn, creator),
        capabilities=frozenset({"organization.provision"}),
    )
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"initial-policy-race-{uuid4().hex}"),
    )
    identity = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="controller-race@example.test",
        password="initial controller concurrency password",
    )
    command = ProvisionNativeOrganizationCommand(
        organization_key="initial-policy-race",
        display_name="Concurrent Clinic",
        identity_authority_id=authority_id,
        native_identity_id=identity.native_identity_id,
        provenance_reference="initial-policy-race",
        idempotency_key="one-clinic",
    )
    commands = PostgresNativePlatformProvisioningCommands(platform_control_session_factory)
    locker = Connection[Any].connect(pg_conninfo)
    locker.execute("SELECT id FROM request_engine.principals WHERE id=%s FOR UPDATE", (creator,))
    tasks = [
        asyncio.create_task(commands.provision_native_organization(actor, command))
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
            assert not any(task.done() for task in tasks), "creator lock was bypassed"
            assert asyncio.get_running_loop().time() < deadline, "both connections must contend"
            await asyncio.sleep(0.01)
    finally:
        locker.rollback()
        locker.close()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
    result = results[0]
    assert isinstance(result, NativeOrganizationResult), results
    assert results[1] == result
    assert admin_conn.execute("SELECT count(*) FROM request_engine.organizations").fetchone() == (
        1,
    )
    assert admin_conn.execute(
        "SELECT initial_controller_policy_key "
        "FROM request_engine.organization_root_provisioning_facts"
    ).fetchall() == [("tenant-controller-v2",)]
    assert admin_conn.execute(
        "SELECT count(*), count(DISTINCT capability_key) "
        "FROM request_engine.principal_authority_grants WHERE principal_id=%s AND status='active'",
        (result.controller_principal_id,),
    ).fetchone() == (34, 34)
    # The older staff-root trigger replaces seven non-delegable grants and
    # retains their revoked provenance; those are not duplicate active grants.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND status='revoked'",
        (result.controller_principal_id,),
    ).fetchone() == (7,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND provenance_reference LIKE 'policy:tenant-controller-v2;root:%%' "
        "AND granted_by_principal_id=%s AND status='active'",
        (result.controller_principal_id, creator),
    ).fetchone() == (26,)


def test_v2_adds_only_explicit_agent_read(admin_conn: Connection[Any]) -> None:
    policies = dict(
        admin_conn.execute(
            "SELECT policy_key, grants FROM request_engine.initial_controller_policies"
        ).fetchall()
    )
    v1 = policies["tenant-controller-v1"]
    v2 = policies["tenant-controller-v2"]
    assert v2 == [
        *v1,
        {
            "capability_key": "agent.read",
            "authority_plane": "tenant_control",
            "delegable": True,
        },
    ]
    assert admin_conn.execute(
        "SELECT revision FROM request_engine.initial_controller_policies "
        "WHERE policy_key='tenant-controller-v2'"
    ).fetchone() == (2,)
    definition = capability_definition("agent.read")
    assert definition is not None and definition.authority_plane.value == "tenant_control"
