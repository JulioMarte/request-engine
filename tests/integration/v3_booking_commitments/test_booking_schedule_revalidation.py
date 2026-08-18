from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.platform.db.session import SessionFactory

from .test_booking_commitments import _book_command, _create_fixture

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
                      AND position('FOR UPDATE OF r' in query) > 0
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
    fixture = _create_fixture(admin_conn)
    reservations = PostgresReservationCommands(app_session_factory)
    start_at = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)
    command = _book_command(
        fixture,
        subject_party_id=fixture.subject_party_id,
        start_at=start_at,
    )

    # The fixture has a Monday 09:00-12:00 America/Santo_Domingo schedule;
    # 13:00 UTC is therefore initially a valid 09:00 local slot.
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

        with pytest.raises(AppointmentUnavailable):
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
