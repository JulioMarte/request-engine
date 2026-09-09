from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from httpx import AsyncClient, Response

from .f5_recovery_support import seed_replacement_resource
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth


class AlternateContextualSupply:
    def __init__(self, resource_id: UUID, assignment_id: UUID) -> None:
        self.resource_id = resource_id
        self.assignment_id = assignment_id


def seed_alternate_contextual_supply(
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> AlternateContextualSupply:
    resource_id = seed_replacement_resource(conn, sandbox)
    assignment = conn.execute(
        """
        SELECT id
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s
          AND resource_id = %s
          AND location_id = %s
          AND status = 'active'
        ORDER BY lower(effective_during) DESC
        LIMIT 1
        """,
        (sandbox.organization_id, resource_id, sandbox.location_id),
    ).fetchone()
    assert assignment is not None
    assignment_id = cast(UUID, assignment[0])
    conn.execute(
        "INSERT INTO request_engine.booking_context_terms "
        "(organization_id,resource_location_assignment_id,offering_version_id,effective_during,"
        "amount,currency,planned_duration_minutes) "
        "VALUES (%s,%s,%s,tstzrange('2026-01-01T00:00:00Z',NULL,'[)'),%s,'DOP',5)",
        (sandbox.organization_id, assignment_id, sandbox.offering_version_id, Decimal("4000")),
    )
    return AlternateContextualSupply(resource_id, assignment_id)


def seed_incident_for_proposal(
    conn: PgConnection,
    sandbox: TenantSandbox,
    proposal: dict[str, Any],
) -> UUID:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    row = conn.execute(
        "INSERT INTO request_engine.operational_recovery_incidents "
        "(organization_id,service_queue_id,resource_id,location_id,status,impact_kind,"
        "source_revision,source_fingerprint,current_proposal_id,last_assessed_at) "
        "VALUES (%s,%s,%s,%s,'open','capacity_shortfall',%s,%s,%s,clock_timestamp()) "
        "RETURNING id",
        (
            sandbox.organization_id,
            sandbox.queue_id,
            sandbox.resource_id,
            sandbox.location_id,
            checkpoint["recovery_source_revision"],
            proposal["source_fingerprint"],
            UUID(cast(str, proposal["id"])),
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def replace_resource(
    client: AsyncClient,
    sandbox: TenantSandbox,
    *,
    incident_id: UUID,
    proposal: dict[str, Any],
    reservation_id: UUID,
    idempotency_key: str,
) -> Response:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return await client.post(
        f"/v1/operational-recovery/incidents/{incident_id}/replace-resource",
        json={
            "expected_source_revision": checkpoint["recovery_source_revision"],
            "proposal_id": proposal["id"],
            "reservation_id": str(reservation_id),
            "expected_source_fingerprint": proposal["source_fingerprint"],
            "expected_proposal_fingerprint": proposal["proposal_fingerprint"],
            "allow_subject_override": False,
        },
        headers=auth(sandbox, idempotency_key=idempotency_key),
    )
