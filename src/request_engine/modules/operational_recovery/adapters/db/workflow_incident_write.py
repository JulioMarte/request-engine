from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import incident_from_row
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
)


async def insert_incident(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    source_revision: int,
    source_fingerprint: str,
    impact_kind: RecoveryImpactKind,
    escalation_level: int,
    current_proposal_id: UUID | None,
) -> RecoveryIncident:
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.operational_recovery_incidents (
                        organization_id, service_queue_id, resource_id, location_id,
                        impact_kind, escalation_level, source_revision, source_fingerprint,
                        current_proposal_id, last_assessed_at
                    ) VALUES (
                        :organization_id, :service_queue_id, :resource_id, :location_id,
                        :impact_kind, :escalation_level, :source_revision, :source_fingerprint,
                        :current_proposal_id, clock_timestamp()
                    ) RETURNING *
                    """
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                    "impact_kind": impact_kind.value,
                    "escalation_level": escalation_level,
                    "source_revision": source_revision,
                    "source_fingerprint": source_fingerprint,
                    "current_proposal_id": current_proposal_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return incident_from_row(cast(RowMapping, row))


async def update_incident(
    session: AsyncSession,
    *,
    organization_id: UUID,
    incident_id: UUID,
    source_revision: int,
    source_fingerprint: str,
    impact_kind: RecoveryImpactKind,
    escalation_level: int,
    current_proposal_id: UUID | None,
    resolve: bool,
) -> RecoveryIncident:
    row = (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.operational_recovery_incidents
                    SET impact_kind = :impact_kind,
                        escalation_level = :escalation_level,
                        source_revision = :source_revision,
                        source_fingerprint = :source_fingerprint,
                        current_proposal_id = :current_proposal_id,
                        status = CASE WHEN :resolve THEN 'resolved' ELSE status END,
                        resolved_at = CASE WHEN :resolve THEN clock_timestamp() ELSE NULL END,
                        last_assessed_at = clock_timestamp(), revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :organization_id AND id = :incident_id
                    RETURNING *
                    """
                ),
                {
                    "organization_id": organization_id,
                    "incident_id": incident_id,
                    "impact_kind": impact_kind.value,
                    "escalation_level": escalation_level,
                    "source_revision": source_revision,
                    "source_fingerprint": source_fingerprint,
                    "current_proposal_id": current_proposal_id,
                    "resolve": resolve,
                },
            )
        )
        .mappings()
        .one()
    )
    return incident_from_row(cast(RowMapping, row))
