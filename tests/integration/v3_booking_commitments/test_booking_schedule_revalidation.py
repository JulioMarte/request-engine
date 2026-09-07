from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    PostgresContextualReservationCommands,
)
from request_engine.modules.booking.application.errors import AppointmentOptionStale
from request_engine.platform.db.session import SessionFactory

from .booking_revalidation_fixture import contextual_book_command, create_fixture

PgConnection = Connection[Any]


def _conninfo() -> str:
    return " ".join(
        (
            f"host={os.environ.get('PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('PGPORT', '5432')}",
            f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}",
            f"user={os.environ.get('PGUSER', 'request_engine')}",
            f"password={os.environ.get('PGPASSWORD', 'request_engine')}",
        )
    )


def _wait_until_booking_waits_on_resource_lock() -> None:
    deadline = time.monotonic() + 5
    observer: PgConnection = psycopg.connect(_conninfo(), autocommit=True)
    try:
        while time.monotonic() < deadline:
            row = observer.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock'
                      AND position('FROM request_engine.resources' in query) > 0
                      AND position('FOR UPDATE' in query) > 0
                )
                """
            ).fetchone()
            if row == (True,):
                return
            time.sleep(0.01)
    finally:
        observer.close()
    raise AssertionError("booking never reached the expected Resource row lock")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_i27_booking_revalidates_schedule_after_resource_lock(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = create_fixture(admin_conn)
    reservations = PostgresContextualReservationCommands(app_session_factory)
    start_at = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)
    command = await contextual_book_command(
        fixture,
        app_session_factory,
        start_at=start_at,
    )

    # The option was valid when discovered. While booking waits on the Resource
    # lock, availability changes and bumps Resource provenance; the command must
    # be rejected as stale before any Reservation or CapacityClaim is committed.
    writer: PgConnection = psycopg.connect(_conninfo(), autocommit=False)
    try:
        writer.execute(
            """
            SELECT id
            FROM request_engine.resources
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, fixture.resource_id),
        ).fetchone()

        booking_task = asyncio.create_task(reservations.book_appointment(command))
        await asyncio.wait_for(
            asyncio.to_thread(_wait_until_booking_waits_on_resource_lock),
            timeout=6,
        )

        writer.execute(
            """
            INSERT INTO request_engine.schedule_exceptions (
                organization_id, resource_id, during, exception_kind, reason
            ) VALUES (
                %s, %s, tstzrange(%s, %s, '[)'), 'unavailable',
                'I27 post-plan schedule invalidation'
            )
            """,
            (fixture.organization_id, fixture.resource_id, start_at, end_at),
        )
        writer.commit()

        with pytest.raises(AppointmentOptionStale):
            await asyncio.wait_for(booking_task, timeout=5)
    finally:
        writer.rollback()
        writer.close()

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
          AND offering_version_id = %s
          AND subject_party_id = %s
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.subject_party_id,
        ),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND resource_id = %s
        """,
        (fixture.organization_id, fixture.resource_id),
    ).fetchone() == (0,)
