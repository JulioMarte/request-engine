from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from httpx import AsyncClient

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import (
    book_commitments,
    restrict_source_to_first_slots,
    seed_replacement_resource,
)
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


@dataclass(frozen=True, slots=True)
class RecoveryWorld:
    reservations: tuple[UUID, ...]
    slots: tuple[dict[str, Any], ...]
    replacement_resource_id: UUID
    scheduled_workload_id: UUID
    walk_in_workload_id: UUID


async def prepare_recovery_world(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    capacity_slots: int = 6,
) -> RecoveryWorld:
    booking_sandbox = five_minute_sandbox(conn, sandbox)
    seed_today_schedule(conn, booking_sandbox)
    scheduled_id, walk_id = await configure_projection(client, booking_sandbox)
    reservations, slots = await book_commitments(client, conn, booking_sandbox)
    replacement = seed_replacement_resource(conn, booking_sandbox)
    restrict_source_to_first_slots(
        conn,
        booking_sandbox,
        slots,
        count=capacity_slots,
    )
    return RecoveryWorld(
        reservations=tuple(reservations),
        slots=tuple(slots),
        replacement_resource_id=replacement,
        scheduled_workload_id=scheduled_id,
        walk_in_workload_id=walk_id,
    )
