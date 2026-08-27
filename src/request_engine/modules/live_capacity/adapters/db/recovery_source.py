from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.adapters.db.recovery_fingerprint import (
    source_fingerprint,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    assemble_live_capacity_projection,
    existing_work,
    has_open_interruption,
)
from request_engine.modules.live_capacity.application.recovery_assessment import (
    build_recovery_checkpoint,
    recovery_pressure,
)
from request_engine.modules.live_capacity.application.recovery_policy import (
    affected_recovery_commitments,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacitySource,
)
from request_engine.platform.db.read_snapshot import postgres_snapshot_session, tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryCapacitySource(RecoveryCapacitySource):
    """Owner-controlled F4 recovery view; F5 receives no Booking/DB internals."""

    def __init__(self, session_factory: SessionFactory, sources: LiveCapacitySources) -> None:
        self._session_factory = session_factory
        self._sources = sources

    async def assess_recovery_capacity(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryCapacityAssessment:
        async with tenant_read_snapshot(self._session_factory, organization_id) as read_snapshot:
            snapshot = await capture_projection_snapshot(
                read_snapshot,
                sources=self._sources,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
            )
            projection = assemble_live_capacity_projection(snapshot)
            session = postgres_snapshot_session(read_snapshot)
            revisions = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT r.availability_revision, l.operational_revision
                            FROM request_engine.resources r
                            JOIN request_engine.locations l
                              ON l.organization_id = r.organization_id
                             AND l.id = :location_id
                            WHERE r.organization_id = :organization_id
                              AND r.id = :resource_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "resource_id": snapshot.policy.resource_id,
                            "location_id": snapshot.policy.location_id,
                        },
                    )
                )
                .mappings()
                .one()
            )

        planned = tuple(snapshot.booking.planned_same_day_work)
        live_work = existing_work(snapshot)
        checkpoint = build_recovery_checkpoint(
            snapshot,
            resource_availability_revision=cast(int, revisions["availability_revision"]),
            location_operational_revision=cast(int, revisions["operational_revision"]),
        )
        committed, shortfall, live_pressure = recovery_pressure(projection)
        open_interruption = has_open_interruption(snapshot)
        open_resource_activity = snapshot.delivery.open_resource_activity is not None

        return RecoveryCapacityAssessment(
            service_queue_id=service_queue_id,
            resource_id=snapshot.policy.resource_id,
            location_id=snapshot.policy.location_id,
            observed_at=snapshot.observed_at,
            horizon_end=snapshot.booking.horizon_end,
            executable_capacity_seconds=projection.remaining_operational_seconds,
            committed_capacity_seconds=committed,
            shortfall_seconds=shortfall,
            source_fingerprint=source_fingerprint(
                policy_id=snapshot.policy.id,
                policy_revision=checkpoint.projection_policy_revision,
                resource_availability_revision=checkpoint.resource_availability_revision,
                location_operational_revision=checkpoint.location_operational_revision,
                intervals=snapshot.booking.remaining_intervals,
                planned=planned,
                work_items=live_work,
                has_open_interruption=open_interruption,
                has_open_resource_activity=open_resource_activity,
            ),
            checkpoint=checkpoint,
            affected_commitments=affected_recovery_commitments(
                planned,
                snapshot.booking.remaining_intervals,
                shortfall,
                live_pressure_seconds=live_pressure,
            ),
        )
