from uuid import UUID

from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.adapters.db.recovery_fingerprint import (
    source_fingerprint,
    source_snapshot,
)
from request_engine.modules.live_capacity.adapters.db.recovery_revision_reader import (
    read_recovery_revisions,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    assemble_live_capacity_projection,
    existing_work,
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
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
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
            resource_revision, location_revision, recovery_revision = await read_recovery_revisions(
                read_snapshot,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                snapshot=snapshot,
            )

        planned = tuple(snapshot.booking.planned_same_day_work)
        live_work = existing_work(snapshot)
        checkpoint = build_recovery_checkpoint(
            snapshot,
            resource_availability_revision=resource_revision,
            location_operational_revision=location_revision,
            recovery_source_revision=recovery_revision,
        )
        committed, scheduled_shortfall, live_shortfall = recovery_pressure(projection)
        shortfall = max(scheduled_shortfall, live_shortfall)
        live_pressure = max(live_shortfall - scheduled_shortfall, 0)
        evidence = source_snapshot(
            observed_at=snapshot.observed_at,
            horizon_end=snapshot.booking.horizon_end,
            policy_id=snapshot.policy.id,
            policy_revision=checkpoint.projection_policy_revision,
            resource_availability_revision=checkpoint.resource_availability_revision,
            location_operational_revision=checkpoint.location_operational_revision,
            recovery_source_revision=checkpoint.recovery_source_revision,
            intervals=snapshot.booking.remaining_intervals,
            planned=planned,
            work_items=live_work,
            queue=snapshot.queue,
            delivery=snapshot.delivery,
            projection=projection,
            live_pressure_seconds=live_pressure,
        )
        return RecoveryCapacityAssessment(
            service_queue_id=service_queue_id,
            resource_id=snapshot.policy.resource_id,
            location_id=snapshot.policy.location_id,
            observed_at=snapshot.observed_at,
            horizon_end=snapshot.booking.horizon_end,
            projection_state=projection.state,
            projection_reasons=projection.reasons,
            executable_capacity_seconds=projection.remaining_operational_seconds,
            committed_capacity_seconds=committed,
            scheduled_shortfall_seconds=scheduled_shortfall,
            live_shortfall_seconds=live_shortfall,
            shortfall_seconds=shortfall,
            source_fingerprint=source_fingerprint(evidence),
            source_snapshot=evidence,
            checkpoint=checkpoint,
            affected_commitments=affected_recovery_commitments(
                planned,
                snapshot.booking.remaining_intervals,
                scheduled_shortfall,
            ),
        )
