from dataclasses import replace
from datetime import datetime
from uuid import uuid4

import psycopg
import pytest

from request_engine.modules.booking.adapters.db.arrival_estimate_commands import (
    PostgresArrivalEstimateCommands,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    record_arrival_estimate,
)
from request_engine.modules.booking.application.errors import (
    ReservationNotConfirmed,
    ReservationNotFound,
    ReservationRevisionConflict,
    SubjectAuthorityRequired,
)
from request_engine.modules.booking.contracts.arrival_estimates import ReservationArrivalEstimate
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict

from ._arrival_estimate_support import (
    ArrivalWorld,
    PgConnection,
    active_rows,
    arrival_command,
    arrival_eta,
)
from ._arrival_estimate_world import create_arrival_world, reservation_revision

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


async def _record(
    commands: PostgresArrivalEstimateCommands,
    world: ArrivalWorld,
    *,
    revision: int,
    key: str,
    override: bool = True,
    eta: datetime | None = None,
) -> ReservationArrivalEstimate:
    return await record_arrival_estimate(
        commands,
        arrival_command(
            world,
            eta=eta if eta is not None else arrival_eta(20),
            revision=revision,
            key=key,
            override=override,
        ),
    )


@pytest.mark.asyncio
async def test_rejects_cancelled_missing_reservations_and_insert_backstop(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    cancelled = create_arrival_world(admin_conn, status="cancelled")
    missing = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)

    with pytest.raises(ReservationNotConfirmed):
        await _record(
            commands,
            cancelled,
            revision=reservation_revision(admin_conn, cancelled),
            key=f"eta-{uuid4().hex}",
        )
    with pytest.raises(ReservationNotFound):
        await _record(
            commands,
            replace(missing, reservation_id=uuid4()),
            revision=1,
            key=f"eta-{uuid4().hex}",
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "INSERT INTO request_engine.reservation_arrival_estimates (organization_id,"
            " reservation_id, estimated_arrival_at, source_kind)"
            " VALUES (%s, %s, now(), 'operator')",
            (cancelled.organization_id, cancelled.reservation_id),
        )
    assert active_rows(admin_conn, cancelled) == []


@pytest.mark.asyncio
async def test_estimate_history_is_immutable(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    await _record(commands, world, revision=1, key=f"eta-{uuid4().hex}")
    await _record(commands, world, revision=2, key=f"eta-{uuid4().hex}")

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.reservation_arrival_estimates SET estimated_arrival_at = now()"
            " WHERE organization_id = %s AND reservation_id = %s",
            (world.organization_id, world.reservation_id),
        )


@pytest.mark.asyncio
async def test_revision_authority_and_idempotency_fencing(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    world = create_arrival_world(admin_conn)
    commands = PostgresArrivalEstimateCommands(session_factory)
    key = f"eta-{uuid4().hex}"

    with pytest.raises(ReservationRevisionConflict):
        await _record(commands, world, revision=7, key=key)
    with pytest.raises(SubjectAuthorityRequired):
        await _record(commands, world, revision=1, key=key, override=False)
    recorded = await _record(commands, world, revision=1, key=key, eta=arrival_eta(20))
    replayed = await _record(
        commands,
        world,
        revision=1,
        key=key,
        eta=recorded.estimated_arrival_at,
    )
    assert replayed.estimate_id == recorded.estimate_id
    assert len(active_rows(admin_conn, world)) == 1
    with pytest.raises(IdempotencyConflict):
        await _record(commands, world, revision=2, key=key, eta=arrival_eta(45))
