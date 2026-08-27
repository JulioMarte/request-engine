from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.workflow_incident_queries import (
    get_incident_row,
    get_open_incident_row,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_write import (
    insert_incident,
    update_incident,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryImpactKind,
    RecoveryIncident,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRecoveryIncidentStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_incident(
        self, *, organization_id: UUID, incident_id: UUID
    ) -> RecoveryIncident | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await get_incident_row(
                session,
                organization_id=organization_id,
                incident_id=incident_id,
            )

    async def get_open_incident(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> RecoveryIncident | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await get_open_incident_row(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
            )

    async def upsert_assessment(
        self,
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
        resolve: bool,
    ) -> RecoveryIncident:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            existing = await get_open_incident_row(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                lock=True,
            )
            if existing is None:
                if resolve:
                    raise LookupError("cannot resolve a recovery scope without an open incident")
                return await insert_incident(
                    session,
                    organization_id=organization_id,
                    service_queue_id=service_queue_id,
                    resource_id=resource_id,
                    location_id=location_id,
                    source_revision=source_revision,
                    source_fingerprint=source_fingerprint,
                    impact_kind=impact_kind,
                    escalation_level=escalation_level,
                    current_proposal_id=current_proposal_id,
                )
            return await update_incident(
                session,
                organization_id=organization_id,
                incident_id=existing.id,
                source_revision=source_revision,
                source_fingerprint=source_fingerprint,
                impact_kind=impact_kind,
                escalation_level=escalation_level,
                current_proposal_id=current_proposal_id,
                resolve=resolve,
            )
