from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient, Response
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]
_SIGNING_KEY = b"request-engine-e2e-journey-signing-key"
_BOOKING_CAPABILITIES = frozenset(
    {
        "appointments.find_slots",
        "appointments.book",
        "appointments.read",
        "appointments.cancel",
        "appointments.reschedule",
    }
)
_QUEUE_CAPABILITIES = frozenset({"queue.list", "queue.status", "queue.join", "queue.leave"})
_STAFF_CAPABILITIES = frozenset(
    {
        "business.get_info",
        "catalog.search_offerings",
        "catalog.get_offering_details",
        "appointments.find_slots",
        "appointments.book",
        "appointments.read",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm_attendance",
        "appointments.subject_override",
        "queue.list",
        "queue.status",
        "queue.join",
        "queue.leave",
        "queue.call_next",
        "queue.subject_override",
        "waitlist.join",
        "waitlist.read",
        "waitlist.leave",
        "waitlist.subject_override",
        "requests.submit",
        "requests.read",
        "requests.cancel",
        "requests.party_override",
        "reminders.create_plan",
        "reminders.read",
        "reminders.cancel_plan",
        "reminders.subject_override",
    }
)
_REQUEST_CAPABILITIES = frozenset(
    {"requests.submit", "requests.read", "requests.cancel", "requests.party_override"}
)


@dataclass(frozen=True, slots=True)
class Person:
    principal_id: UUID
    party_id: UUID
    token: str


@dataclass(frozen=True, slots=True)
class Practice:
    organization_id: UUID
    staff_principal_id: UUID
    staff_token: str
    location_id: UUID
    offering_id: UUID
    offering_key: str
    offering_version_id: UUID
    resource_id: UUID
    queue_id: UUID
    request_key: str
    people: tuple[Person, ...]


class BearerResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise AuthenticationRequired
        actor = self._actors.get(authorization.removeprefix("Bearer "))
        if actor is None:
            raise AuthenticationRequired
        return actor


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...] = ()) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _grant_representation(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID, party_id: UUID, scope_key: str
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'self', %s, clock_timestamp() + interval '1 day')
        """,
        (organization_id, principal_id, party_id, scope_key),
    )


def _seed_practice(conn: PgConnection, *, people_count: int = 8) -> Practice:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, public_profile
        ) VALUES (%s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            f"e2e-practice-{suffix}",
            f"E2E Practice {suffix[:8]}",
            json.dumps({"summary": "E2E multi-user practice"}),
        ),
    )
    staff_principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"staff-{suffix}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo', %s::jsonb)
        RETURNING id
        """,
        (organization_id, f"main-{suffix}", json.dumps({"city": "Puerto Plata"})),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
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
            json.dumps({"price": 2500, "currency": "DOP"}),
        ),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 2500, 'DOP')
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
        (organization_id, f"physician-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, 'Dr. E2E', 'exclusive', 1)
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
    request_key = f"contact_request_{suffix}"
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, 'Contact request', true)
        RETURNING id
        """,
        (organization_id, request_key),
    )
    input_schema = json.dumps(
        {
            "type": "object",
            "required": ["message"],
            "additionalProperties": False,
            "properties": {"message": {"type": "string", "minLength": 1}},
        }
    )
    result_schema = json.dumps({"type": "object", "properties": {}})
    conn.execute(
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version,
            input_schema, result_schema
        ) VALUES (%s, %s, 1, %s::jsonb, %s::jsonb)
        """,
        (organization_id, definition_id, input_schema, result_schema),
    )
    people: list[Person] = []
    for index in range(people_count):
        party_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.parties (
                organization_id, party_kind, display_name
            ) VALUES (%s, 'person', %s)
            RETURNING id
            """,
            (organization_id, f"Patient {index + 1}"),
        )
        principal_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.principals (
                organization_id, principal_kind, external_subject
            ) VALUES (%s, 'human', %s)
            RETURNING id
            """,
            (organization_id, f"patient-{index + 1}-{suffix}"),
        )
        for scope_key in ("appointments.book", "appointments.manage", "queue.join", "queue.manage"):
            _grant_representation(
                conn,
                organization_id=organization_id,
                principal_id=principal_id,
                party_id=party_id,
                scope_key=scope_key,
            )
        people.append(Person(principal_id, party_id, f"patient-{index + 1}-{suffix}"))
    return Practice(
        organization_id,
        staff_principal_id,
        f"staff-{suffix}",
        location_id,
        offering_id,
        offering_key,
        offering_version_id,
        resource_id,
        queue_id,
        request_key,
        tuple(people),
    )


def _actors(*practices: Practice) -> dict[str, ActorContext]:
    actors: dict[str, ActorContext] = {}
    for practice in practices:
        actors[practice.staff_token] = ActorContext(
            practice.organization_id, practice.staff_principal_id, _STAFF_CAPABILITIES
        )
        for person in practice.people:
            actors[person.token] = ActorContext(
                practice.organization_id,
                person.principal_id,
                _BOOKING_CAPABILITIES | _QUEUE_CAPABILITIES,
            )
    return actors


def _client(session_factory: SessionFactory, actors: dict[str, ActorContext]) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(actors),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(token: str, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _first_slot(client: AsyncClient, practice: Practice, token: str) -> dict[str, object]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(practice.offering_version_id),
            "location_id": str(practice.location_id),
            "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    slots = response.json()
    assert slots
    return cast(dict[str, object], slots[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_e2e_many_patients_race_for_one_slot_then_capacity_recovers(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    practice = _seed_practice(e2e_admin_conn, people_count=8)
    async with _client(e2e_session_factory, _actors(practice)) as client:
        slot = await _first_slot(client, practice, practice.people[0].token)

        async def attempt(person: Person) -> tuple[Person, Response]:
            return person, await client.post(
                "/v1/appointments",
                json={"option_id": slot["option_id"], "subject_party_id": str(person.party_id)},
                headers=_auth(person.token, idempotency_key=f"race-{uuid4().hex}"),
            )

        results = await asyncio.gather(*(attempt(person) for person in practice.people))
        winners = [
            (person, response) for person, response in results if response.status_code == 201
        ]
        losers = [(person, response) for person, response in results if response.status_code != 201]
        assert len(winners) == 1
        assert len(losers) == 7
        assert all(response.status_code == 409 for _, response in losers)
        winner, booked = winners[0]
        reservation_id = UUID(booked.json()["id"])
        read = await client.get(f"/v1/appointments/{reservation_id}", headers=_auth(winner.token))
        assert read.status_code == 200
        cancelled = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json={"expected_revision": read.json()["revision"], "reason": "free the slot"},
            headers=_auth(winner.token, idempotency_key=f"cancel-{uuid4().hex}"),
        )
        assert cancelled.status_code == 200
        next_person = losers[0][0]
        recovered = await client.post(
            "/v1/appointments",
            json={"option_id": slot["option_id"], "subject_party_id": str(next_person.party_id)},
            headers=_auth(next_person.token, idempotency_key=f"recover-{uuid4().hex}"),
        )
        assert recovered.status_code == 201, recovered.text
    active_count = e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s AND status = 'confirmed'
        """,
        (practice.organization_id,),
    ).fetchone()
    assert active_count == (1,)


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_e2e_two_tenants_cannot_observe_or_mutate_each_other(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    practice_a = _seed_practice(e2e_admin_conn, people_count=2)
    practice_b = _seed_practice(e2e_admin_conn, people_count=2)
    async with _client(e2e_session_factory, _actors(practice_a, practice_b)) as client:
        business_a, business_b = await asyncio.gather(
            client.get("/v1/business", headers=_auth(practice_a.staff_token)),
            client.get("/v1/business", headers=_auth(practice_b.staff_token)),
        )
        assert business_a.status_code == business_b.status_code == 200
        assert business_a.json()["organization_id"] == str(practice_a.organization_id)
        assert business_b.json()["organization_id"] == str(practice_b.organization_id)
        catalog_a = await client.get("/v1/catalog/offerings", headers=_auth(practice_a.staff_token))
        assert {item["offering_key"] for item in catalog_a.json()} == {practice_a.offering_key}
        foreign_slots = await client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(practice_b.offering_version_id),
                "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
                "window_end": datetime(2030, 1, 7, 14, 0, tzinfo=UTC).isoformat(),
            },
            headers=_auth(practice_a.staff_token),
        )
        assert foreign_slots.status_code == 404
        request_from_a = await client.post(
            f"/v1/requests/definitions/{practice_a.request_key}/submit",
            json={
                "payload": {"message": "tenant A"},
                "requester_party_id": str(practice_a.people[0].party_id),
            },
            headers=_auth(practice_a.staff_token, idempotency_key=f"request-a-{uuid4().hex}"),
        )
        assert request_from_a.status_code == 201, request_from_a.text
        request_id = request_from_a.json()["request"]["id"]
        foreign_read = await client.get(
            f"/v1/requests/{request_id}", headers=_auth(practice_b.staff_token)
        )
        assert foreign_read.status_code == 404


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_e2e_queue_preserves_fifo_across_many_users_and_replays_call_next(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    practice = _seed_practice(e2e_admin_conn, people_count=6)
    async with _client(e2e_session_factory, _actors(practice)) as client:
        joined_ids: list[str] = []
        for person in practice.people:
            joined = await client.post(
                f"/v1/queues/{practice.queue_id}/join",
                json={
                    "subject_party_id": str(person.party_id),
                    "offering_id": str(practice.offering_id),
                },
                headers=_auth(person.token, idempotency_key=f"join-{uuid4().hex}"),
            )
            assert joined.status_code == 201, joined.text
            joined_ids.append(joined.json()["id"])
        called_ids: list[str] = []
        for _ in practice.people:
            key = f"call-{uuid4().hex}"
            called = await client.post(
                f"/v1/queues/{practice.queue_id}/call-next",
                headers=_auth(practice.staff_token, idempotency_key=key),
            )
            replay = await client.post(
                f"/v1/queues/{practice.queue_id}/call-next",
                headers=_auth(practice.staff_token, idempotency_key=key),
            )
            assert called.status_code == replay.status_code == 200
            assert replay.json() == called.json()
            called_ids.append(called.json()["id"])
        assert called_ids == joined_ids
        empty = await client.post(
            f"/v1/queues/{practice.queue_id}/call-next",
            headers=_auth(practice.staff_token, idempotency_key=f"empty-{uuid4().hex}"),
        )
        assert empty.status_code == 200 and empty.json() is None
    call_events = e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = 'queue.entry_called.v1'
        """,
        (practice.organization_id,),
    ).fetchone()
    assert call_events == (len(practice.people),)


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_e2e_public_request_submit_replay_conflict_read_and_cancel(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    practice = _seed_practice(e2e_admin_conn, people_count=2)
    actor = ActorContext(
        practice.organization_id, practice.staff_principal_id, _REQUEST_CAPABILITIES
    )
    async with _client(e2e_session_factory, {practice.staff_token: actor}) as client:
        key = f"submit-{uuid4().hex}"
        body = {
            "payload": {"message": "Please contact me"},
            "requester_party_id": str(practice.people[0].party_id),
        }
        submitted = await client.post(
            f"/v1/requests/definitions/{practice.request_key}/submit",
            json=body,
            headers=_auth(practice.staff_token, idempotency_key=key),
        )
        replay = await client.post(
            f"/v1/requests/definitions/{practice.request_key}/submit",
            json=body,
            headers=_auth(practice.staff_token, idempotency_key=key),
        )
        conflict = await client.post(
            f"/v1/requests/definitions/{practice.request_key}/submit",
            json={**body, "payload": {"message": "different payload"}},
            headers=_auth(practice.staff_token, idempotency_key=key),
        )
        assert submitted.status_code == replay.status_code == 201
        assert replay.json() == submitted.json()
        assert conflict.status_code == 409
        request_view = submitted.json()["request"]
        request_id = request_view["id"]
        read = await client.get(f"/v1/requests/{request_id}", headers=_auth(practice.staff_token))
        assert read.status_code == 200 and read.json()["id"] == request_id
        cancel_key = f"cancel-{uuid4().hex}"
        cancelled = await client.post(
            f"/v1/requests/{request_id}/cancel",
            json={"reason": "done", "expected_revision": request_view["revision"]},
            headers=_auth(practice.staff_token, idempotency_key=cancel_key),
        )
        cancel_replay = await client.post(
            f"/v1/requests/{request_id}/cancel",
            json={"reason": "done", "expected_revision": request_view["revision"]},
            headers=_auth(practice.staff_token, idempotency_key=cancel_key),
        )
        assert cancelled.status_code == cancel_replay.status_code == 200
        assert cancel_replay.json() == cancelled.json()
        assert cancelled.json()["status"] == "cancelled"
