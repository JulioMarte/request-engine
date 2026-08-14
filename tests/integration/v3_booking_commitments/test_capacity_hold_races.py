# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
    confirm_capacity_hold,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    CapacityHoldRevisionConflict,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.holds import CapacityHold
from request_engine.platform.db.session import SessionFactory

from .test_booking_commitments import (
    BookingFixture,
    _choice,
    _create_fixture,
    _create_party,
)

PgConnection = Connection[Any]
RaceCoroutine = Coroutine[Any, Any, object]
RaceResult = object | BaseException


def _hold_command_for_subject(
    fixture: BookingFixture,
    *,
    subject_party_id: UUID,
    start_at: datetime,
) -> AcquireCapacityHoldCommand:
    return AcquireCapacityHoldCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        resources=_choice(fixture),
        idempotency_key=f"hold-race-{uuid4().hex}",
        allow_subject_override=True,
    )


async def _start_behind_resource_lock(
    admin_conn: PgConnection,
    *,
    organization_id: UUID,
    resource_id: UUID,
    coroutines: tuple[RaceCoroutine, ...],
) -> list[RaceResult]:
    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
              FROM request_engine.resources
             WHERE organization_id = %s
               AND id = %s
             FOR UPDATE
            """,
            (organization_id, resource_id),
        ).fetchone()
        tasks: list[asyncio.Task[object]] = [
            asyncio.create_task(coroutine) for coroutine in coroutines
        ]
        await asyncio.sleep(0.1)

    return list(await asyncio.gather(*tasks, return_exceptions=True))


async def _start_behind_hold_lock(
    admin_conn: PgConnection,
    *,
    organization_id: UUID,
    hold_id: UUID,
    coroutines: tuple[RaceCoroutine, ...],
) -> list[RaceResult]:
    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
              FROM request_engine.capacity_holds
             WHERE organization_id = %s
               AND id = %s
             FOR UPDATE
            """,
            (organization_id, hold_id),
        ).fetchone()
        tasks: list[asyncio.Task[object]] = [
            asyncio.create_task(coroutine) for coroutine in coroutines
        ]
        await asyncio.sleep(0.1)

    return list(await asyncio.gather(*tasks, return_exceptions=True))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_concurrent_conflicting_holds_commit_exactly_one_capacity_owner(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    competitor_party_id = _create_party(
        admin_conn,
        fixture.organization_id,
        "Concurrent competing patient",
    )
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)

    first_result, second_result = await _start_behind_resource_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        resource_id=fixture.resource_id,
        coroutines=(
            acquire_capacity_hold(
                commitments,
                _hold_command_for_subject(
                    fixture,
                    subject_party_id=fixture.subject_party_id,
                    start_at=start_at,
                ),
            ),
            acquire_capacity_hold(
                commitments,
                _hold_command_for_subject(
                    fixture,
                    subject_party_id=competitor_party_id,
                    start_at=start_at,
                ),
            ),
        ),
    )

    successes = [
        result for result in (first_result, second_result) if isinstance(result, CapacityHold)
    ]
    failures = [
        result for result in (first_result, second_result) if isinstance(result, BaseException)
    ]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], AppointmentUnavailable)

    active_holds = admin_conn.execute(
        """
        SELECT h.id, h.subject_party_id
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = %s
           AND h.status = 'active'
           AND h.during = tstzrange(%s, %s, '[)')
         ORDER BY h.id
        """,
        (
            fixture.organization_id,
            start_at,
            start_at + timedelta(minutes=30),
        ),
    ).fetchall()
    assert len(active_holds) == 1
    assert active_holds[0][0] == successes[0].id

    live_claims = admin_conn.execute(
        """
        SELECT c.hold_id, c.reservation_id, c.status
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = %s
           AND c.resource_id = %s
           AND c.during && tstzrange(%s, %s, '[)')
           AND c.status = 'active'
         ORDER BY c.id
        """,
        (
            fixture.organization_id,
            fixture.resource_id,
            start_at,
            start_at + timedelta(minutes=30),
        ),
    ).fetchall()
    assert live_claims == [(successes[0].id, None, "active")]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_concurrent_hold_confirmation_creates_exactly_one_reservation(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    hold = await acquire_capacity_hold(
        commitments,
        _hold_command_for_subject(
            fixture,
            subject_party_id=fixture.subject_party_id,
            start_at=start_at,
        ),
    )

    first_result, second_result = await _start_behind_hold_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        hold_id=hold.id,
        coroutines=(
            confirm_capacity_hold(
                commitments,
                ConfirmCapacityHoldCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    hold_id=hold.id,
                    expected_revision=hold.revision,
                    idempotency_key=f"confirm-race-a-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            confirm_capacity_hold(
                commitments,
                ConfirmCapacityHoldCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    hold_id=hold.id,
                    expected_revision=hold.revision,
                    idempotency_key=f"confirm-race-b-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
        ),
    )

    successes = [
        result for result in (first_result, second_result) if isinstance(result, Reservation)
    ]
    failures = [
        result for result in (first_result, second_result) if isinstance(result, BaseException)
    ]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CapacityHoldRevisionConflict)

    graph = admin_conn.execute(
        """
        SELECT h.status,
               h.revision,
               (SELECT count(*)
                  FROM request_engine.reservations r
                 WHERE r.organization_id = h.organization_id
                   AND r.id = %s),
               (SELECT count(*)
                  FROM request_engine.capacity_claims c
                 WHERE c.organization_id = h.organization_id
                   AND c.hold_id = h.id
                   AND c.reservation_id = %s
                   AND c.status = 'active'),
               (SELECT count(*)
                  FROM request_engine.capacity_claims c
                 WHERE c.organization_id = h.organization_id
                   AND c.hold_id = h.id
                   AND c.reservation_id IS NULL
                   AND c.status = 'active')
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = %s
           AND h.id = %s
        """,
        (
            successes[0].id,
            successes[0].id,
            fixture.organization_id,
            hold.id,
        ),
    ).fetchone()
    assert graph == ("consumed", hold.revision + 1, 1, 1, 0)
