from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import LiteralString, cast
from uuid import UUID, uuid4

from fastapi import Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from . import operational_support as support

ALL_PUBLIC_CAPABILITIES = frozenset(
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
        "requests.submit",
        "requests.read",
        "requests.record_result",
        "requests.complete",
        "requests.cancel",
        "requests.fail",
        "requests.party_override",
    }
)


@dataclass(frozen=True, slots=True)
class TenantSandbox:
    organization_id: UUID
    organization_key: str
    display_name: str
    principal_id: UUID
    token: str
    party_id: UUID
    location_id: UUID
    offering_id: UUID
    offering_key: str
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    queue_id: UUID
    request_key: str


class SandboxResolver:
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
    conn: support.PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def seed_tenant_sandbox(conn: support.PgConnection, prefix: str) -> TenantSandbox:
    suffix = uuid4().hex
    organization_key = f"{prefix}-{suffix}"
    display_name = f"{prefix} {suffix[:10]}"
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, public_profile
        ) VALUES (%s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            organization_key,
            display_name,
            json.dumps({"e2e_marker": organization_key}),
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
        (organization_id, f"staff-{suffix}"),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix[:8]}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo', '{}'::jsonb)
        RETURNING id
        """,
        (organization_id, f"location-{suffix}", f"Location {suffix[:8]}"),
    )
    offering_key = f"offering-{suffix}"
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name, description
        ) VALUES (%s, %s, %s, 'Tenant isolation E2E offering')
        RETURNING id
        """,
        (organization_id, offering_key, f"Offering {suffix[:8]}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy, public_data
        ) VALUES (%s, %s, 1, 30, true, true, %s::jsonb, '{}'::jsonb)
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
        (organization_id, f"capability-{suffix}", f"Capability {suffix[:8]}"),
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
        ) VALUES (%s, %s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"resource-{suffix}", f"Resource {suffix[:8]}"),
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
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, location_id, offering_id, queue_key, display_name
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            organization_id,
            location_id,
            offering_id,
            f"queue-{suffix}",
            f"Queue {suffix[:8]}",
        ),
    )
    request_key = f"request_{suffix}"
    request_definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, %s, true)
        RETURNING id
        """,
        (organization_id, request_key, f"Request {suffix[:8]}"),
    )
    input_schema = json.dumps(
        {
            "type": "object",
            "required": ["message"],
            "additionalProperties": False,
            "properties": {"message": {"type": "string", "minLength": 1}},
        }
    )
    result_schema = json.dumps(
        {
            "type": "object",
            "required": ["accepted"],
            "additionalProperties": False,
            "properties": {"accepted": {"type": "boolean"}},
        }
    )
    conn.execute(
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema, result_schema
        ) VALUES (%s, %s, 1, %s::jsonb, %s::jsonb)
        """,
        (organization_id, request_definition_id, input_schema, result_schema),
    )
    return TenantSandbox(
        organization_id=organization_id,
        organization_key=organization_key,
        display_name=display_name,
        principal_id=principal_id,
        token=f"token-{suffix}",
        party_id=party_id,
        location_id=location_id,
        offering_id=offering_id,
        offering_key=offering_key,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        queue_id=queue_id,
        request_key=request_key,
    )


def actors_for(*sandboxes: TenantSandbox) -> dict[str, ActorContext]:
    return {
        sandbox.token: ActorContext(
            organization_id=sandbox.organization_id,
            principal_id=sandbox.principal_id,
            capabilities=ALL_PUBLIC_CAPABILITIES,
        )
        for sandbox in sandboxes
    }


def client_for(
    session_factory: SessionFactory,
    *sandboxes: TenantSandbox,
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(actors_for(*sandboxes)),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def auth(sandbox: TenantSandbox, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {sandbox.token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def first_slot(client: AsyncClient, sandbox: TenantSandbox) -> dict[str, object]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    slots = response.json()
    assert isinstance(slots, list) and slots
    return cast(dict[str, object], slots[0])
