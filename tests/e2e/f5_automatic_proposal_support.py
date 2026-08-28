from dataclasses import dataclass
from typing import cast
from uuid import UUID

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


@dataclass(frozen=True, slots=True)
class AutomaticProposalFact:
    id: UUID
    source_revision: int
    source_fingerprint: str
    proposal_fingerprint: str
    created_by_principal_id: UUID | None


def automatic_proposals(
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> tuple[AutomaticProposalFact, ...]:
    rows = conn.execute(
        "SELECT id,source_revision,source_fingerprint,proposal_fingerprint,"
        "created_by_principal_id FROM request_engine.operational_recovery_proposals "
        "WHERE organization_id=%s AND service_queue_id=%s AND creation_kind='automatic' "
        "ORDER BY source_revision,id",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchall()
    return tuple(
        AutomaticProposalFact(
            id=cast(UUID, row[0]),
            source_revision=cast(int, row[1]),
            source_fingerprint=cast(str, row[2]),
            proposal_fingerprint=cast(str, row[3]),
            created_by_principal_id=cast(UUID | None, row[4]),
        )
        for row in rows
    )


def incident_proposal_id(conn: PgConnection, sandbox: TenantSandbox) -> UUID | None:
    row = conn.execute(
        "SELECT current_proposal_id FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s AND service_queue_id=%s AND status <> 'resolved'",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(UUID | None, row[0])
