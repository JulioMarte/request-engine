import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.errors import LockNotAvailable

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]


class SingleActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer represented":
            raise AuthenticationRequired
        return self._actor


def _connect(*, autocommit: bool = False) -> PgConnection:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
    return psycopg.connect(
        f"host={host} port={port} dbname={database} user={user} password={password}",
        autocommit=autocommit,
    )


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _wait_until_booking_is_blocked_on_resource_lock(
    observer: PgConnection,
) -> None:
    for _ in range(200):
        row = observer.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND wait_event_type = 'Lock'
              AND query LIKE '%%FROM request_engine.resources r%%'
              AND query LIKE '%%FOR UPDATE OF r%%'
            """
        ).fetchone()
        assert row is not None
        if cast(int, row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Booking never reached the post-authority Resource lock barrier")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_booking_holds_representation_authority_until_material_command_commit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Booking authority race')
        RETURNING id
        """,
        (f"booking-authority-race-{suffix}",),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"represented-{suffix}"),
    )
    subject_party_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Protected Patient')
        RETURNING id
        """,
        (organization_id,),
    )
    location_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Protected consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 30})),
    )
    capability_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician')
        RETURNING id
        """,
        (organization_id, f"physician-{suffix}"),
    )
    requirement_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Dr. Authority', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id),
    )
    representation_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key,
            valid_from,
            valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'appointments.book',
            clock_timestamp() - interval '1 minute',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, subject_party_id),
    )

    actor = ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=frozenset({"booking.find_slots", "booking.book_appointment"}),
    )
    app = create_app(
        session_factory=session_factory,
        actor_resolver=SingleActorResolver(actor),
    )

    blocker = _connect()
    revoker = _connect()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            slots_response = await client.get(
                "/v1/appointments/slots",
                params={
                    "offering_version_id": str(offering_version_id),
                    "location_id": str(location_id),
                    "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
                    "window_end": datetime(2026, 8, 17, 14, 0, tzinfo=UTC).isoformat(),
                },
                headers={"Authorization": "Bearer represented"},
            )
            assert slots_response.status_code == 200
            slot = slots_response.json()[0]
            booking_body = {
                "option_id": slot["option_id"],
                "subject_party_id": str(subject_party_id),
            }

            blocker.execute(
                """
                SELECT id
                FROM request_engine.resources
                WHERE organization_id = %s AND id = %s
                FOR UPDATE
                """,
                (organization_id, resource_id),
            )

            booking_task = asyncio.create_task(
                client.post(
                    "/v1/appointments",
                    json=booking_body,
                    headers={
                        "Authorization": "Bearer represented",
                        "Idempotency-Key": f"booking-authority-race-{suffix}",
                    },
                )
            )

            await _wait_until_booking_is_blocked_on_resource_lock(admin_conn)

            revoker.execute("SET LOCAL lock_timeout = '250ms'")
            with pytest.raises(LockNotAvailable):
                revoker.execute(
                    """
                    UPDATE request_engine.representations
                    SET status = 'revoked', revision = revision + 1
                    WHERE organization_id = %s AND id = %s
                    """,
                    (organization_id, representation_id),
                )
            revoker.rollback()

            blocker.commit()
            booked = await asyncio.wait_for(booking_task, timeout=5)
            assert booked.status_code == 201
            reservation_id = UUID(booked.json()["id"])

            updated = revoker.execute(
                """
                UPDATE request_engine.representations
                SET status = 'revoked', revision = revision + 1
                WHERE organization_id = %s AND id = %s
                """,
                (organization_id, representation_id),
            )
            assert updated.rowcount == 1
            revoker.commit()

            rejected_after_revoke = await client.post(
                "/v1/appointments",
                json=booking_body,
                headers={
                    "Authorization": "Bearer represented",
                    "Idempotency-Key": f"booking-after-revoke-{suffix}",
                },
            )
            assert rejected_after_revoke.status_code == 403
            assert rejected_after_revoke.json()["error"]["code"] == "party_authority_required"

        persisted = admin_conn.execute(
            """
            SELECT organization_id, subject_party_id, status, revision
            FROM request_engine.reservations
            WHERE id = %s
            """,
            (reservation_id,),
        ).fetchone()
        assert persisted == (organization_id, subject_party_id, "confirmed", 1)

        authority_audit = admin_conn.execute(
            """
            SELECT details -> 'subject_authority'
            FROM request_engine.audit_records
            WHERE organization_id = %s
              AND aggregate_kind = 'Reservation'
              AND aggregate_id = %s
              AND command_name = 'booking.book_appointment'
            """,
            (organization_id, reservation_id),
        ).fetchone()
        assert authority_audit is not None
        assert authority_audit[0]["representation_id"] == str(representation_id)
    finally:
        if not blocker.closed:
            blocker.rollback()
        if not revoker.closed:
            revoker.rollback()
        blocker.close()
        revoker.close()
