from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import incident_from_row
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
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_engine.operational_recovery_incidents
                            WHERE organization_id = :organization_id AND id = :incident_id
                            """
                        ),
                        {"organization_id": organization_id, "incident_id": incident_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else incident_from_row(cast(RowMapping, row))

    async def get_open_incident(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> RecoveryIncident | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_engine.operational_recovery_incidents
                            WHERE organization_id = :organization_id
                              AND service_queue_id = :service_queue_id
                              AND status <> 'resolved'
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "service_queue_id": service_queue_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else incident_from_row(cast(RowMapping, row))

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
            existing = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM request_engine.operational_recovery_incidents
                            WHERE organization_id = :organization_id
                              AND service_queue_id = :service_queue_id
                              AND status <> 'resolved'
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "service_queue_id": service_queue_id,
                        },
                    )
                ).scalar_one_or_none()
            )
            if existing is None and resolve:
                raise LookupError("cannot resolve a recovery scope without an open incident")
            if existing is None:
                return await _insert_incident(
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
            return await _update_incident(
                session,
                organization_id=organization_id,
                incident_id=cast(UUID, existing),
                source_revision=source_revision,
                source_fingerprint=source_fingerprint,
                impact_kind=impact_kind,
                escalation_level=escalation_level,
                current_proposal_id=current_proposal_id,
                resolve=resolve,
            )


async def _insert_incident(session: object, **values: object) -> RecoveryIncident:
    from sqlalchemy.ext.asyncio import AsyncSession

    db = cast(AsyncSession, session)
    row = (
        (
            await db.execute(
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
                {**values, "impact_kind": cast(RecoveryImpactKind, values["impact_kind"]).value},
            )
        )
        .mappings()
        .one()
    )
    return incident_from_row(cast(RowMapping, row))


async def _update_incident(session: object, **values: object) -> RecoveryIncident:
    from sqlalchemy.ext.asyncio import AsyncSession

    db = cast(AsyncSession, session)
    resolve = cast(bool, values.pop("resolve"))
    row = (
        (
            await db.execute(
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
                {**values, "resolve": resolve, "impact_kind": cast(RecoveryImpactKind, values["impact_kind"]).value},
            )
        )
        .mappings()
        .one()
    )
    return incident_from_row(cast(RowMapping, row))
