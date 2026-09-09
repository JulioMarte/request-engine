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

_SIGNING_KEY = b"request-engine-e2e-tenant-signing-key"
ALL_PUBLIC_CAPABILITIES = frozenset(
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
OVERRIDE_CAPABILITIES = frozenset(
    {
        "appointments.subject_override",
        "queue.subject_override",
        "waitlist.subject_override",
        "requests.party_override",
        "reminders.subject_override",
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


def _uuid_row(conn: support.PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
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
        (organization_key, display_name, json.dumps({"e2e_marker": organization_key})),
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
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix[:8]}"),
    )
    for scope_key in (
        "appointments.book",
        "appointments.manage",
        "queue.join",
        "queue.manage",
        "waitlist.join",
        "waitlist.manage",
        "requests.submit",
        "requests.manage",
        "reminders.manage",
    ):
        conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, valid_until
            ) VALUES (%s, %s, %s, 'self', %s, clock_timestamp() + interval '1 day')
            """,
            (organization_id, principal_id, party_id, scope_key),
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
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
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
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}", f"Resource {suffix[:8]}"),
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
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (organization_id, location_id, offering_id, f"queue-{suffix}", f"Queue {suffix[:8]}"),
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
    result_schema = json.dumps({"type": "object", "properties": {}})
    conn.execute(
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version,
            input_schema, result_schema
        ) VALUES (%s, %s, 1, %s::jsonb, %s::jsonb)
        """,
        (organization_id, request_definition_id, input_schema, result_schema),
    )
    return TenantSandbox(
        organization_id,
        organization_key,
        display_name,
        principal_id,
        f"token-{suffix}",
        party_id,
        location_id,
        offering_id,
        offering_key,
        offering_version_id,
        requirement_id,
        resource_id,
        queue_id,
        request_key,
    )


def actor_for(sandbox: TenantSandbox, *, allow_overrides: bool = True) -> ActorContext:
    capabilities = (
        ALL_PUBLIC_CAPABILITIES
        if allow_overrides
        else ALL_PUBLIC_CAPABILITIES - OVERRIDE_CAPABILITIES
    )
    return ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=sandbox.principal_id,
        capabilities=capabilities,
    )


def client_for(session_factory: SessionFactory, *sandboxes: TenantSandbox) -> AsyncClient:
    actors = {sandbox.token: actor_for(sandbox) for sandbox in sandboxes}
    app = create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(actors),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def client_with_actors(
    session_factory: SessionFactory, actors: dict[str, ActorContext]
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(actors),
        appointment_option_signing_key=_SIGNING_KEY,
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
