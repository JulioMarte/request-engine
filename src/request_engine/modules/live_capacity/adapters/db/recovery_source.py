import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    capacity_intervals,
    scheduled_commitments,
)
from request_engine.modules.live_capacity.application.recovery_policy import (
    affected_recovery_commitments,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacityCheckpoint,
    RecoveryCapacitySource,
    RecoveryCommitmentCheckpoint,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity
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
            projection = project_live_capacity(
                observed_at=snapshot.observed_at,
                intervals=capacity_intervals(snapshot),
                work_items=(),
                scheduled_work_items=scheduled_commitments(snapshot),
            )
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
        resource_revision = cast(int, revisions["availability_revision"])
        location_revision = cast(int, revisions["operational_revision"])
        checkpoint = RecoveryCapacityCheckpoint(
            projection_policy_revision=snapshot.policy.revision,
            resource_availability_revision=resource_revision,
            location_operational_revision=location_revision,
            commitments=tuple(
                RecoveryCommitmentCheckpoint(
                    reservation_id=item.reservation_id,
                    revision=item.reservation_revision,
                    starts_at=item.planned_starts_at,
                    ends_at=item.planned_ends_at,
                )
                for item in sorted(
                    planned,
                    key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
                )
            ),
        )
        executable = projection.remaining_operational_seconds
        committed = projection.scheduled_committed_workload_seconds or 0
        shortfall = max(committed - executable, 0)
        affected = affected_recovery_commitments(
            planned,
            snapshot.booking.remaining_intervals,
            shortfall,
        )
        source_fingerprint = _source_fingerprint(
            policy_id=snapshot.policy.id,
            policy_revision=checkpoint.projection_policy_revision,
            resource_availability_revision=checkpoint.resource_availability_revision,
            location_operational_revision=checkpoint.location_operational_revision,
            intervals=snapshot.booking.remaining_intervals,
            planned=planned,
        )
        return RecoveryCapacityAssessment(
            service_queue_id=service_queue_id,
            resource_id=snapshot.policy.resource_id,
            location_id=snapshot.policy.location_id,
            observed_at=snapshot.observed_at,
            horizon_end=snapshot.booking.horizon_end,
            executable_capacity_seconds=executable,
            committed_capacity_seconds=committed,
            shortfall_seconds=shortfall,
            source_fingerprint=source_fingerprint,
            checkpoint=checkpoint,
            affected_commitments=affected,
        )


def _source_fingerprint(
    *,
    policy_id: UUID,
    policy_revision: int,
    resource_availability_revision: int,
    location_operational_revision: int,
    intervals: tuple[OperationalAvailabilityInterval, ...],
    planned: tuple[PlannedWorkloadFact, ...],
) -> str:
    payload = {
        "policy_id": str(policy_id),
        "policy_revision": policy_revision,
        "resource_availability_revision": resource_availability_revision,
        "location_operational_revision": location_operational_revision,
        "intervals": [
            [item.starts_at.isoformat(), item.ends_at.isoformat()] for item in intervals
        ],
        "planned": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.reservation_revision,
                "offering_version_id": str(item.offering_version_id),
                "subject_party_id": str(item.subject_party_id),
                "starts_at": item.planned_starts_at.isoformat(),
                "ends_at": item.planned_ends_at.isoformat(),
                "contextual_commitment": item.contextual_commitment,
            }
            for item in sorted(
                planned,
                key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
            )
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
