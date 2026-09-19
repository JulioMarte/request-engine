"""E2 identity-aware onboarding readiness: falsifiable PostgreSQL proofs.

Each proof names the defect that would turn it red. The oracle is a direct admin
SELECT over ``principal_authority_grants`` / ``initial_controller_policies`` and
the production continuity predicate ``principal_is_effective_tenant_controller``,
never the reader under test.
"""

from typing import Any, cast
from uuid import UUID

import pytest
from agent_governance_support import provision_root
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.onboarding_identity_reader import (
    PostgresOnboardingIdentityFactsReader,
)
from request_engine.platform.db.session import SessionFactory, set_tenant_context

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_CONTROL_CAPABILITIES = (
    "staff.manage_membership",
    "staff.manage_authority",
    "identity.bind",
)


def _revoke_capability(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability_key: str,
) -> None:
    rowcount = conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked',
               revision = revision + 1,
               revoked_at = clock_timestamp(),
               revoked_by_principal_id = %s
         WHERE organization_id = %s
           AND principal_id = %s
           AND capability_key = %s
           AND status = 'active'
        """,
        (principal_id, organization_id, principal_id, capability_key),
    ).rowcount
    assert rowcount == 1


def _sqlstate(exc: DBAPIError) -> str | None:
    return cast(str | None, getattr(exc.orig, "sqlstate", None))


def _policy_missing_capabilities(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    policy_key: str,
) -> set[str]:
    rows = conn.execute(
        """
        SELECT g.capability_key
          FROM request_engine.initial_controller_policies AS policy,
               jsonb_to_recordset(policy.grants)
                   AS g(capability_key text, authority_plane text, delegable boolean)
         WHERE policy.policy_key = %s
           AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS active
                    WHERE active.organization_id = %s
                      AND active.principal_id = %s
                      AND active.capability_key = g.capability_key
                      AND active.status = 'active'
               )
        """,
        (policy_key, organization_id, principal_id),
    ).fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.asyncio
async def test_missing_effective_controller_reports_identity_not_ready(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, root_id, _authority_id = provision_root(admin_conn)
    _revoke_capability(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        capability_key="identity.bind",
    )

    effective = admin_conn.execute(
        "SELECT request_engine.principal_is_effective_tenant_controller(%s, %s)",
        (organization_id, root_id),
    ).fetchone()
    assert effective == (False,)
    active_control = admin_conn.execute(
        """
        SELECT count(DISTINCT capability_key)
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s AND status = 'active'
           AND capability_key = ANY(%s)
        """,
        (organization_id, root_id, list(_CONTROL_CAPABILITIES)),
    ).fetchone()
    assert active_control == (2,)

    reader = PostgresOnboardingIdentityFactsReader(command_session_factory)
    facts = await reader.read_identity_facts(organization_id=organization_id)

    assert facts.identity.active_controller is False
    assert facts.identity.authenticatable_controller is False


@pytest.mark.asyncio
async def test_foreign_organization_is_denied_by_definer_guard(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, root_id, _authority_id = provision_root(admin_conn)
    foreign_organization_id, _foreign_party, _foreign_root, _foreign_authority = provision_root(
        admin_conn
    )
    reader = PostgresOnboardingIdentityFactsReader(command_session_factory)

    own = await reader.read_identity_facts(organization_id=organization_id)
    assert own.identity.active_controller is True
    assert own.identity.authenticatable_controller is True

    async with command_session_factory() as session, session.begin():
        await set_tenant_context(session, organization_id)
        with pytest.raises(DBAPIError) as denied:
            await session.execute(
                text("SELECT request_engine.read_onboarding_identity_facts(:organization_id)"),
                {"organization_id": foreign_organization_id},
            )
    assert _sqlstate(denied.value) == "42501"
    assert foreign_organization_id != organization_id
    assert root_id is not None


@pytest.mark.asyncio
async def test_recorded_policy_with_missing_capability_is_not_ready(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    admin_conn.execute(
        "SELECT set_config('request_engine.initial_controller_policy', "
        "'tenant-controller-v3', false)"
    )
    try:
        organization_id, _party_id, root_id, _authority_id = provision_root(admin_conn)
    finally:
        admin_conn.execute(
            "SELECT set_config('request_engine.initial_controller_policy', '', false)"
        )

    recorded = admin_conn.execute(
        "SELECT initial_controller_policy_key "
        "FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert recorded == ("tenant-controller-v3",)

    reader = PostgresOnboardingIdentityFactsReader(command_session_factory)
    ready = await reader.read_identity_facts(organization_id=organization_id)
    assert ready.tenant_control.recorded_policy_key == "tenant-controller-v3"
    assert ready.tenant_control.current_policy_ready is True
    assert ready.policy_revision == 3
    assert ready.staff_administration.available is True

    _revoke_capability(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        capability_key="catalog.manage",
    )
    missing = _policy_missing_capabilities(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key="tenant-controller-v3",
    )
    assert missing == {"catalog.manage"}

    blocked = await reader.read_identity_facts(organization_id=organization_id)
    assert blocked.tenant_control.current_policy_ready is False
    assert blocked.identity.active_controller is True
    assert blocked.identity.authenticatable_controller is True
