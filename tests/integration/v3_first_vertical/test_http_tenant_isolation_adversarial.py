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

_BOOKING_CAPABILITIES = frozenset(
    {
        "booking.find_slots",
        "booking.book_appointment",
        "booking.read",
        "booking.cancel_reservation",
        "booking.reschedule_reservation",
        "appointments.subject_override",
    }
)


@dataclass(frozen=True, slots=True)
class TenantBookingFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
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
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> TenantBookingFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"http-isolation-{label}-{suffix}", f"HTTP Isolation {label}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{label}-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Patient {label}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{label}-{suffix}", f"Office {label}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"consult-{label}-{suffix}", f"Consultation {label}"),
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
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"physician-{label}-{suffix}", f"Physician {label}"),
    )
    _uuid_row(
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
        ) VALUES (%s, %s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{label}-{suffix}", f"Doctor {label}"),
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
    return TenantBookingFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        resource_id=resource_id,
    )


def _actor(fixture: TenantBookingFixture) -> ActorContext:
    return ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_BOOKING_CAPABILITIES,
    )


def _error_shape(response: Response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, cast(str, error["code"]), cast(str, error["resolution"])


def _client(
    session_factory: SessionFactory,
    tenant_a: TenantBookingFixture,
    tenant_b: TenantBookingFixture,
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(
            {
                "tenant-a": _actor(tenant_a),
                "tenant-b": _actor(tenant_b),
            }
        ),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _first_slot(
    client: AsyncClient,
    fixture: TenantBookingFixture,
    token: str,
) -> dict[str, object]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(fixture.offering_version_id),
            "location_id": str(fixture.location_id),
            "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2026, 8, 17, 14, 0, tzinfo=UTC).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    slots = response.json()
    assert slots
    return cast(dict[str, object], slots[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_booking_identifiers_are_indistinguishable_from_nonexistent_ids(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a")
    tenant_b = _fixture(admin_conn, "b")
    headers_a = {"Authorization": "Bearer tenant-a"}
    headers_b = {"Authorization": "Bearer tenant-b"}

    async with _client(session_factory, tenant_a, tenant_b) as client:
        foreign_slots = await client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(tenant_b.offering_version_id),
                "location_id": str(tenant_b.location_id),
                "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
                "window_end": datetime(2026, 8, 17, 14, 0, tzinfo=UTC).isoformat(),
            },
            headers=headers_a,
        )
        nonexistent_slots = await client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(uuid4()),
                "location_id": str(uuid4()),
                "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
                "window_end": datetime(2026, 8, 17, 14, 0, tzinfo=UTC).isoformat(),
            },
            headers=headers_a,
        )
        assert _error_shape(foreign_slots) == _error_shape(nonexistent_slots)

        slot_b = await _first_slot(client, tenant_b, "tenant-b")
        booked_b = await client.post(
            "/v1/appointments",
            json={
                "option_id": slot_b["option_id"],
                "subject_party_id": str(tenant_b.subject_party_id),
            },
            headers={**headers_b, "Idempotency-Key": f"book-b-{uuid4().hex}"},
        )
        assert booked_b.status_code == 201
        reservation_b = UUID(booked_b.json()["id"])
        initial_revision = cast(int, booked_b.json()["revision"])

        foreign_read = await client.get(
            f"/v1/appointments/{reservation_b}",
            headers=headers_a,
        )
        nonexistent_read = await client.get(
            f"/v1/appointments/{uuid4()}",
            headers=headers_a,
        )
        assert _error_shape(foreign_read) == _error_shape(nonexistent_read)
        assert _error_shape(foreign_read) == (404, "reservation_not_found", "refresh_and_retry")

        foreign_cancel = await client.post(
            f"/v1/appointments/{reservation_b}/cancel",
            json={"reason": "cross-tenant attack", "expected_revision": initial_revision},
            headers={**headers_a, "Idempotency-Key": f"attack-{uuid4().hex}"},
        )
        nonexistent_cancel = await client.post(
            f"/v1/appointments/{uuid4()}/cancel",
            json={"reason": "nonexistent control", "expected_revision": initial_revision},
            headers={**headers_a, "Idempotency-Key": f"control-{uuid4().hex}"},
        )
        assert _error_shape(foreign_cancel) == _error_shape(nonexistent_cancel)
        assert _error_shape(foreign_cancel) == (404, "reservation_not_found", "refresh_and_retry")

        owner_read = await client.get(
            f"/v1/appointments/{reservation_b}",
            headers=headers_b,
        )
        assert owner_read.status_code == 200
        assert owner_read.json()["status"] == "confirmed"
        assert owner_read.json()["revision"] == initial_revision

    persisted = admin_conn.execute(
        """
        SELECT organization_id, status, revision
        FROM request_engine.reservations
        WHERE id = %s
        """,
        (reservation_b,),
    ).fetchone()
    assert persisted == (tenant_b.organization_id, "confirmed", initial_revision)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_tenant_bound_appointment_option_cannot_be_replayed_by_another_tenant(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a-option")
    tenant_b = _fixture(admin_conn, "b-option")

    async with _client(session_factory, tenant_a, tenant_b) as client:
        slot_b = await _first_slot(client, tenant_b, "tenant-b")
        response = await client.post(
            "/v1/appointments",
            json={
                "option_id": slot_b["option_id"],
                "subject_party_id": str(tenant_a.subject_party_id),
            },
            headers={
                "Authorization": "Bearer tenant-a",
                "Idempotency-Key": f"foreign-option-{uuid4().hex}",
            },
        )
        assert _error_shape(response) == (422, "appointment_option_invalid", "fix_request")
        assert response.json()["error"]["message"] == (
            "the appointment option is invalid for this request"
        )
        assert response.json()["error"]["details"] == {}

    cross_tenant_reservations = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
          AND offering_version_id = %s
        """,
        (tenant_a.organization_id, tenant_b.offering_version_id),
    ).fetchone()
    assert cross_tenant_reservations == (0,)
