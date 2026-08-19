# pyright: reportPrivateUsage=false

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.holds import CapacityHold
from request_engine.platform.db.session import SessionFactory

from .test_booking_commitments import _choice, _create_fixture
from .test_cross_tenant_shared_capacity import _book, _hold, _two_bound_tenants
from .test_g18_adversarial_races import (
    _force_shared_root_winner,
    _start_blocked_hold_confirmation,
)

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_hold_confirmation_released_before_authoritative_expiry_consumes_hold_once(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R02: confirmation may win only while PostgreSQL still considers the Hold live."""

    fixture = _create_fixture(admin_conn)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    hold = await acquire_capacity_hold(
        commitments,
        AcquireCapacityHoldCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_version_id=fixture.offering_version_id,
            subject_party_id=fixture.subject_party_id,
            location_id=fixture.location_id,
            start_at=start_at,
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
            resources=_choice(fixture),
            idempotency_key=f"g18-live-hold-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )

    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
              FROM request_engine.capacity_holds
             WHERE organization_id = %s AND id = %s
             FOR UPDATE
            """,
            (fixture.organization_id, hold.id),
        ).fetchone()
        confirm_task = await _start_blocked_hold_confirmation(
            monkeypatch,
            admin_conn,
            commitments,
            ConfirmCapacityHoldCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                hold_id=hold.id,
                expected_revision=hold.revision,
                idempotency_key=f"g18-live-confirm-{uuid4().hex}",
                allow_subject_override=True,
            ),
        )
        still_live = admin_conn.execute(
            """
            SELECT expires_at > clock_timestamp()
              FROM request_engine.capacity_holds
             WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, hold.id),
        ).fetchone()
        assert still_live == (True,)

    result = await asyncio.wait_for(confirm_task, timeout=5)
    assert isinstance(result, Reservation)

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
         WHERE h.organization_id = %s AND h.id = %s
        """,
        (result.id, result.id, fixture.organization_id, hold.id),
    ).fetchone()
    assert graph == ("consumed", hold.revision + 1, 1, 1, 0)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.parametrize("winner", ["booking", "hold"])
async def test_direct_booking_vs_foreign_capacity_hold_has_one_owner_in_both_orders(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    winner: str,
) -> None:
    """R26: Booking and a foreign Hold serialize on the same shared capacity root."""

    tenant_a, tenant_b, root_id = _two_bound_tenants(admin_conn)
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    start_at = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)

    booking_race = book_appointment(reservations, _book(tenant_b, start_at))
    hold_race = acquire_capacity_hold(commitments, _hold(tenant_a, start_at))

    if winner == "booking":
        booking_result, hold_result = await _force_shared_root_winner(
            monkeypatch,
            admin_conn,
            winner_organization_id=tenant_b.organization_id,
            winner=booking_race,
            loser=hold_race,
        )
        assert isinstance(booking_result, Reservation)
        assert isinstance(hold_result, AppointmentUnavailable)
    else:
        hold_result, booking_result = await _force_shared_root_winner(
            monkeypatch,
            admin_conn,
            winner_organization_id=tenant_a.organization_id,
            winner=hold_race,
            loser=booking_race,
        )
        assert isinstance(hold_result, CapacityHold)
        assert isinstance(booking_result, AppointmentUnavailable)

    graph = admin_conn.execute(
        """
        SELECT
            (SELECT count(*)
               FROM request_engine.capacity_holds h
              WHERE h.organization_id = %s
                AND h.during = tstzrange(%s, %s, '[)')
                AND h.status = 'active'
                AND h.expires_at > clock_timestamp()),
            (SELECT count(*)
               FROM request_engine.capacity_claims c
               JOIN request_engine.shared_capacity_claim_links link
                 ON link.capacity_claim_id = c.id
              WHERE c.organization_id = %s
                AND c.during = tstzrange(%s, %s, '[)')
                AND c.status = 'active'
                AND link.shared_capacity_identity_id = %s),
            (SELECT count(*)
               FROM request_engine.reservations r
              WHERE r.organization_id = %s
                AND r.during = tstzrange(%s, %s, '[)')
                AND r.status = 'confirmed'),
            (SELECT count(*)
               FROM request_engine.capacity_claims c
               JOIN request_engine.shared_capacity_claim_links link
                 ON link.capacity_claim_id = c.id
              WHERE c.organization_id = %s
                AND c.during = tstzrange(%s, %s, '[)')
                AND c.status = 'active'
                AND link.shared_capacity_identity_id = %s)
        """,
        (
            tenant_a.organization_id,
            start_at,
            end_at,
            tenant_a.organization_id,
            start_at,
            end_at,
            root_id,
            tenant_b.organization_id,
            start_at,
            end_at,
            tenant_b.organization_id,
            start_at,
            end_at,
            root_id,
        ),
    ).fetchone()
    if winner == "booking":
        assert graph == (0, 0, 1, 1)
    else:
        assert graph == (1, 1, 0, 0)
