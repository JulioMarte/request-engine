import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]

_FULL_CAPABILITIES = frozenset(
    {
        "business.read",
        "catalog.read",
        "booking.find_slots",
        "booking.book_appointment",
        "booking.read",
        "booking.cancel_reservation",
        "booking.reschedule_reservation",
        "appointments.subject_override",
        "queue.read",
        "queue.join",
        "queue.leave",
        "queue.call_next",
        "queue.subject_override",
    }
)


@dataclass(frozen=True, slots=True)
class OperationsFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_id: UUID
    offering_key: str
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    queue_id: UUID


class BearerTestActorResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            raise AuthenticationRequired
        actor = self._actors.get(authorization.removeprefix("Bearer "))
        if actor is None:
            raise AuthenticationRequired
        return actor


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_fixture(conn: PgConnection) -> OperationsFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, public_profile
        ) VALUES (%s, 'Doctor Example', %s::jsonb)
        RETURNING id
        """,
        (
            f"operations-{suffix}",
            json.dumps({"phone": "+18095550000", "summary": "Primary care practice"}),
        ),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Patient Example')
        RETURNING id
        """,
        (organization_id,),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo', %s::jsonb)
        RETURNING id
        """,
        (organization_id, f"main-{suffix}", json.dumps({"address": "Puerto Plata"})),
    )
    offering_key = f"consultation-{suffix}"
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name, description
        ) VALUES (%s, %s, 'Medical consultation', 'Thirty minute consultation')
        RETURNING id
        """,
        (organization_id, offering_key),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy, public_data
        ) VALUES (%s, %s, 1, 30, true, true, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            offering_id,
            json.dumps({"slot_step_minutes": 30}),
            json.dumps({"price_note": "Contact office"}),
        ),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (organization_id, offering_version_id),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, 'Dr. Example', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    assignment_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (%s, %s, %s, tstzrange('2000-01-01T00:00:00+00', NULL, '[)'))
        RETURNING id
        """,
        (organization_id, resource_id, location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (organization_id, location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (organization_id, assignment_id),
    )
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, location_id, offering_id, queue_key, display_name
        ) VALUES (%s, %s, %s, %s, 'Walk-in consultation')
        RETURNING id
        """,
        (organization_id, location_id, offering_id, f"walk-in-{suffix}"),
    )
    return OperationsFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_id=offering_id,
        offering_key=offering_key,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        queue_id=queue_id,
    )


def _client(
    session_factory: SessionFactory,
    actors: dict[str, ActorContext],
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver(actors),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_catalog_discovery_and_tenant_capabilities(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "reader": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset({"business.read", "catalog.read"}),
        ),
        "none": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset(),
        ),
    }
    async with _client(session_factory, actors) as client:
        unauthenticated = await client.get("/v1/business")
        forbidden = await client.get(
            "/v1/catalog/offerings",
            headers={"Authorization": "Bearer none"},
        )
        business = await client.get(
            "/v1/business",
            headers={"Authorization": "Bearer reader"},
        )
        offerings = await client.get(
            "/v1/catalog/offerings",
            params={"bookable": "true", "search_text": "Medical"},
            headers={"Authorization": "Bearer reader"},
        )
        details = await client.get(
            f"/v1/catalog/offerings/{fixture.offering_key}",
            headers={"Authorization": "Bearer reader"},
        )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert business.status_code == 200
    assert business.json()["display_name"] == "Doctor Example"
    assert business.json()["locations"][0]["public_data"] == {"address": "Puerto Plata"}
    assert offerings.status_code == 200
    assert len(offerings.json()) == 1
    assert offerings.json()[0]["latest_version"]["id"] == str(fixture.offering_version_id)
    assert details.status_code == 200
    assert details.json()["offering_key"] == fixture.offering_key


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_discover_slot_book_read_and_cancel_idempotently(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_CAPABILITIES,
        )
    }
    auth = {"Authorization": "Bearer agent"}
    async with _client(session_factory, actors) as client:
        slots_response = await client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(fixture.offering_version_id),
                "location_id": str(fixture.location_id),
                "window_start": datetime(2099, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
                "window_end": datetime(2099, 8, 17, 16, 0, tzinfo=UTC).isoformat(),
            },
            headers=auth,
        )
        assert slots_response.status_code == 200
        slots = slots_response.json()
        assert len(slots) == 6
        first = slots[0]
        assert set(first) == {"option_id", "start_at", "end_at", "location_id"}
        booking_key = f"http-book-{uuid4().hex}"
        booking_body = {
            "option_id": first["option_id"],
            "subject_party_id": str(fixture.subject_party_id),
        }
        booked = await client.post(
            "/v1/appointments",
            json=booking_body,
            headers={**auth, "Idempotency-Key": booking_key},
        )
        replay = await client.post(
            "/v1/appointments",
            json=booking_body,
            headers={**auth, "Idempotency-Key": booking_key},
        )
        assert booked.status_code == 201
        assert replay.status_code == 201
        assert replay.json() == booked.json()
        reservation_id = booked.json()["id"]

        read = await client.get(f"/v1/appointments/{reservation_id}", headers=auth)
        assert read.status_code == 200
        assert read.json()["status"] == "confirmed"
        current_revision = cast(int, read.json()["revision"])

        cancel_key = f"http-cancel-{uuid4().hex}"
        cancel_body = {
            "reason": "patient changed plans",
            "expected_revision": current_revision,
        }
        cancelled = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json=cancel_body,
            headers={**auth, "Idempotency-Key": cancel_key},
        )
        cancel_replay = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json=cancel_body,
            headers={**auth, "Idempotency-Key": cancel_key},
        )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancel_replay.json() == cancelled.json()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_queue_join_read_leave_idempotently(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_CAPABILITIES,
        )
    }
    auth = {"Authorization": "Bearer agent"}
    async with _client(session_factory, actors) as client:
        joined = await client.post(
            f"/v1/queues/{fixture.queue_id}/entries",
            json={"subject_party_id": str(fixture.subject_party_id)},
            headers={**auth, "Idempotency-Key": f"queue-join-{uuid4().hex}"},
        )
        assert joined.status_code == 201
        entry_id = joined.json()["id"]

        read = await client.get(f"/v1/queues/{fixture.queue_id}", headers=auth)
        assert read.status_code == 200
        assert read.json()["queue_id"] == str(fixture.queue_id)

        leave_key = f"queue-leave-{uuid4().hex}"
        left = await client.post(
            f"/v1/queues/{fixture.queue_id}/entries/{entry_id}/leave",
            headers={**auth, "Idempotency-Key": leave_key},
        )
        replay = await client.post(
            f"/v1/queues/{fixture.queue_id}/entries/{entry_id}/leave",
            headers={**auth, "Idempotency-Key": leave_key},
        )
    assert left.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == left.json()
