from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.adapters.db.projection_policy_reader import (
    load_active_projection_scope,
    load_configured_estimates,
)
from request_engine.modules.live_capacity.application.errors import (
    InvalidProjectionConfiguration,
    ProjectionScopeNotConfigured,
)
from request_engine.modules.live_capacity.application.estimate_resolution import resolve_estimates
from request_engine.modules.live_capacity.application.projection_snapshot import ProjectionSnapshot
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


async def capture_projection_snapshot(
    snapshot: ReadSnapshot,
    *,
    sources: LiveCapacitySources,
    organization_id: UUID,
    service_queue_id: UUID,
    additional_workload_ids: tuple[UUID, ...] = (),
) -> ProjectionSnapshot:
    session = postgres_snapshot_session(snapshot)
    observed_at = cast(datetime, await session.scalar(text("SELECT clock_timestamp()")))
    policy = await load_active_projection_scope(
        session,
        organization_id=organization_id,
        service_queue_id=service_queue_id,
    )
    if policy is None:
        raise ProjectionScopeNotConfigured(service_queue_id)
    booking = await sources.booking.read_operational_availability(
        snapshot,
        organization_id=organization_id,
        resource_id=policy.resource_id,
        location_id=policy.location_id,
        observed_at=observed_at,
    )
    if not booking.configuration_valid:
        raise InvalidProjectionConfiguration(service_queue_id)
    queue = await sources.queue.read_projection_queue(
        snapshot,
        organization_id=organization_id,
        queue_id=service_queue_id,
        observed_at=observed_at,
    )
    delivery = await sources.delivery.read_projection_delivery(
        snapshot,
        organization_id=organization_id,
        resource_id=policy.resource_id,
        location_id=policy.location_id,
        observed_at=observed_at,
    )
    workload_ids = tuple(
        sorted(set(_workload_ids(queue, delivery)) | set(additional_workload_ids), key=str)
    )
    configured = await load_configured_estimates(
        session,
        organization_id=organization_id,
        workload_ids=workload_ids,
    )
    estimates = await resolve_estimates(
        snapshot,
        delivery=sources.delivery,
        organization_id=organization_id,
        resource_id=policy.resource_id,
        observed_at=observed_at,
        workload_ids=workload_ids,
        configured_seconds=configured,
    )
    return ProjectionSnapshot(observed_at, policy, booking, queue, delivery, estimates)


def _workload_ids(
    queue: QueueProjectionSnapshot,
    delivery: DeliveryProjectionSnapshot,
) -> tuple[UUID, ...]:
    values = {
        item.expected_workload_classification_id
        for item in queue.entries
        if item.expected_workload_classification_id is not None
    }
    if (
        delivery.active_service is not None
        and delivery.active_service.actual_workload_classification_id is not None
    ):
        values.add(delivery.active_service.actual_workload_classification_id)
    return tuple(sorted(values, key=str))
