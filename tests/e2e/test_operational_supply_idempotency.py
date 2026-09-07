from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .operator_journey_support import operator_client, revision
from .tenant_sandbox import auth, seed_tenant_sandbox


def _remove_baseline_supply(conn: PgConnection, organization_id: UUID) -> None:
    conn.execute(
        "DELETE FROM request_engine.resource_location_availability WHERE organization_id = %s",
        (organization_id,),
    )
    conn.execute(
        "DELETE FROM request_engine.resource_location_assignments WHERE organization_id = %s",
        (organization_id,),
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
async def test_assignment_create_replays_once_and_rejects_conflicting_reuse(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "supply-replay")
    _remove_baseline_supply(e2e_admin_conn, sandbox.organization_id)
    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', 'operations.manage_supply',
                  clock_timestamp() + interval '1 day')
        """,
        (sandbox.organization_id, sandbox.principal_id, sandbox.party_id),
    )
    resource_revision = revision(
        e2e_admin_conn,
        "SELECT availability_revision FROM request_engine.resources WHERE id = %s",
        sandbox.resource_id,
    )
    key = f"assignment-replay-{uuid4().hex}"
    body = {
        "authority_party_id": str(sandbox.party_id),
        "resource_id": str(sandbox.resource_id),
        "location_id": str(sandbox.location_id),
        "effective_from": "2026-01-01T00:00:00Z",
        "expected_resource_availability_revision": resource_revision,
    }

    async with operator_client(e2e_session_factory, sandbox) as client:
        created = await client.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=key),
            json=body,
        )
        replay = await client.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=key),
            json=body,
        )
        conflict = await client.post(
            "/v1/operations/resource-assignments",
            headers=auth(sandbox, idempotency_key=key),
            json={**body, "effective_from": "2026-02-01T00:00:00Z"},
        )

    assert created.status_code == 200, created.text
    assert replay.json() == created.json()
    assert conflict.status_code == 409
    assignment_id = UUID(created.json()["assignment_id"])
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.resource_location_assignments WHERE id = %s",
        (assignment_id,),
    ).fetchone() == (1,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE aggregate_kind = 'ResourceLocationAssignment' AND aggregate_id = %s "
        "AND command_name = 'booking.assign_resource_to_location'",
        (assignment_id,),
    ).fetchone() == (1,)
