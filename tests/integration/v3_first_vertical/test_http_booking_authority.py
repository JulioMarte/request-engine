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

_ACTION_CAPABILITIES = frozenset(
    {
        "booking.find_slots",
        "booking.book_appointment",
        "booking.read",
        "booking.cancel_reservation",
        "booking.reschedule_reservation",
    }
)


@dataclass(frozen=True, slots=True)
class AuthorityFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID


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


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> AuthorityFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Authority Practice')
        RETURNING id
        """,
        (f"authority-http-{suffix}",),
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
        VALUES (%s, 'person', 'Protected Patient')
        RETURNING id
        """,
        (organization_id,),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Protected consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
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
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician')
        RETURNING id
        """,
        (organization_id, f"physician-{suffix}"),
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
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Dr. Authority', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id),
    )
    return AuthorityFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _grant(
    conn: PgConnection,
    fixture: AuthorityFixture,
    scope_key: str,
    *,
    authority_kind: str = "authorized_contact",
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, %s, %s, clock_timestamp() + interval '1 day')
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.principal_id,
            fixture.subject_party_id,
            authority_kind,
            scope_key,
        ),
    )


def _client(
    session_factory: SessionFactory,
    fixture: AuthorityFixture,
) -> AsyncClient:
    actors = {
        "delegated": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_ACTION_CAPABILITIES,
        ),
        "operator": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_ACTION_CAPABILITIES | frozenset({"appointments.subject_override"}),
        ),
    }
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(actors),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_booking_requires_current_subject_authority_and_records_provenance(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    delegated = {"Authorization": "Bearer delegated"}
    operator = {"Authorization": "Bearer operator"}

    async with _client(session_factory, fixture) as client:
        slots_response = await client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(fixture.offering_version_id),
                "location_id": str(fixture.location_id),
                "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
                "window_end": datetime(2026, 8, 17, 14, 0, tzinfo=UTC).isoformat(),
            },
            headers=delegated,
        )
        assert slots_response.status_code == 200
        slot = slots_response.json()[0]
        booking_body = {
            "offering_version_id": str(fixture.offering_version_id),
            "subject_party_id": str(fixture.subject_party_id),
            "location_id": str(fixture.location_id),
            "start_at": slot["start_at"],
            "resources": slot["resources"],
        }

        denied = await client.post(
            "/v1/appointments",
            json=booking_body,
            headers={**delegated, "Idempotency-Key": f"denied-{uuid4().hex}"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "subject_authority_required"
        assert denied.json()["error"]["details"]["scope_key"] == "appointments.book"

        book_representation_id = _grant(admin_conn, fixture, "appointments.book")
        manage_representation_id = _grant(admin_conn, fixture, "appointments.manage")
        booked = await client.post(
            "/v1/appointments",
            json=booking_body,
            headers={**delegated, "Idempotency-Key": f"book-{uuid4().hex}"},
        )
        assert booked.status_code == 201
        reservation_id = UUID(booked.json()["id"])

        readable = await client.get(
            f"/v1/appointments/{reservation_id}",
            headers=delegated,
        )
        assert readable.status_code == 200

        admin_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, manage_representation_id),
        )
        read_after_revoke = await client.get(
            f"/v1/appointments/{reservation_id}",
            headers=delegated,
        )
        cancel_after_revoke = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json={"reason": "should not be authorized"},
            headers={**delegated, "Idempotency-Key": f"cancel-denied-{uuid4().hex}"},
        )
        assert read_after_revoke.status_code == 403
        assert cancel_after_revoke.status_code == 403

        operator_read = await client.get(
            f"/v1/appointments/{reservation_id}",
            headers=operator,
        )
        assert operator_read.status_code == 200
        operator_cancel = await client.post(
            f"/v1/appointments/{reservation_id}/cancel",
            json={"reason": "staff cancellation"},
            headers={**operator, "Idempotency-Key": f"cancel-{uuid4().hex}"},
        )
        assert operator_cancel.status_code == 200
        assert operator_cancel.json()["status"] == "cancelled"

    audit_rows = admin_conn.execute(
        """
        SELECT command_name, details
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'Reservation'
          AND aggregate_id = %s
        ORDER BY created_at, id
        """,
        (fixture.organization_id, reservation_id),
    ).fetchall()
    assert [row[0] for row in audit_rows] == [
        "booking.book_appointment",
        "booking.cancel_reservation",
    ]
    book_authority = audit_rows[0][1]["subject_authority"]
    assert book_authority == {
        "mode": "representation",
        "scope_key": "appointments.book",
        "representation_id": str(book_representation_id),
        "authority_kind": "authorized_contact",
    }
    cancel_authority = audit_rows[1][1]["subject_authority"]
    assert cancel_authority == {
        "mode": "operator",
        "scope_key": "appointments.manage",
        "representation_id": None,
        "authority_kind": None,
    }
