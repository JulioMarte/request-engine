from datetime import UTC, datetime, timedelta
from typing import Any, cast

from psycopg import Connection

from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
)
from request_engine.modules.booking.contracts.arrival_estimates import ArrivalEstimateSource

from ._arrival_estimate_world import ArrivalWorld

PgConnection = Connection[Any]


def arrival_command(
    world: ArrivalWorld,
    *,
    eta: datetime,
    source: str,
    revision: int,
    key: str,
    override: bool = True,
) -> RecordArrivalEstimateCommand:
    return RecordArrivalEstimateCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        reservation_id=world.reservation_id,
        estimated_arrival_at=eta,
        source_kind=ArrivalEstimateSource(source),
        idempotency_key=key,
        expected_revision=revision,
        allow_subject_override=override,
    )


def arrival_eta(minutes: int) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def active_rows(conn: PgConnection, world: ArrivalWorld) -> list[tuple[datetime, str, bool]]:
    return cast(
        "list[tuple[datetime, str, bool]]",
        conn.execute(
            "SELECT estimated_arrival_at, source_kind, superseded_at IS NOT NULL"
            " FROM request_engine.reservation_arrival_estimates"
            " WHERE organization_id = %s AND reservation_id = %s"
            " ORDER BY asserted_at, id",
            (world.organization_id, world.reservation_id),
        ).fetchall(),
    )
