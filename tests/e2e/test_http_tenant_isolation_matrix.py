from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .evidence import durable_snapshot
from .http_surface import PUBLIC_HTTP_OPERATIONS, PublicHttpOperation, TenantIsolationMode
from .tenant_sandbox import (
    TenantSandbox,
    actor_for,
    auth,
    client_with_actors,
    first_slot,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@dataclass(frozen=True, slots=True)
class ForeignObjects:
    reservation_id: UUID
    reservation_revision: int
    queue_entry_id: UUID
    queue_entry_revision: int
    waitlist_entry_id: UUID
    waitlist_revision: int
    request_id: UUID
    request_revision: int
    reminder_plan_id: UUID
    reminder_revision: int
    actor_option_id: str


async def _seed_foreign_objects(
    client: AsyncClient,
    admin: support.PgConnection,
    actor_tenant: TenantSandbox,
    foreign_tenant: TenantSandbox,
) -> ForeignObjects:
    actor_slot = await first_slot(client, actor_tenant)
    foreign_slot = await first_slot(client, foreign_tenant)
    booked = await client.post(
        "/v1/appointments",
        json={
            "option_id": foreign_slot["option_id"],
            "subject_party_id": str(foreign_tenant.party_id),
        },
        headers=auth(foreign_tenant, idempotency_key=f"foreign-book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    joined = await client.post(
        f"/v1/queues/{foreign_tenant.queue_id}/join",
        json={
            "subject_party_id": str(foreign_tenant.party_id),
            "offering_id": str(foreign_tenant.offering_id),
        },
        headers=auth(foreign_tenant, idempotency_key=f"foreign-queue-{uuid4().hex}"),
    )
    assert joined.status_code == 201, joined.text
    waitlisted = await client.post(
        "/v1/waitlist",
        json={
            "offering_id": str(foreign_tenant.offering_id),
            "subject_party_id": str(foreign_tenant.party_id),
        },
        headers=auth(foreign_tenant, idempotency_key=f"foreign-waitlist-{uuid4().hex}"),
    )
    assert waitlisted.status_code == 201, waitlisted.text
    submitted = await client.post(
        f"/v1/requests/definitions/{foreign_tenant.request_key}/submit",
        json={
            "payload": {"message": "foreign request"},
            "requester_party_id": str(foreign_tenant.party_id),
        },
        headers=auth(foreign_tenant, idempotency_key=f"foreign-request-{uuid4().hex}"),
    )
    assert submitted.status_code == 201, submitted.text
    support.new_contact_point(
        admin, foreign_tenant.organization_id, foreign_tenant.party_id, "reminder"
    )
    reminder = await client.post(
        "/v1/reminders",
        json={
            "subject_party_id": str(foreign_tenant.party_id),
            "purpose": "medication_reminder",
            "timezone": "America/Santo_Domingo",
            "daily_times": ["08:00:00"],
            "channel_policy": {"channels": ["email"]},
            "template_key": "medication-reminder",
            "template_version": 1,
        },
        headers=auth(foreign_tenant, idempotency_key=f"foreign-reminder-{uuid4().hex}"),
    )
    assert reminder.status_code == 201, reminder.text
    request_view = submitted.json()["request"]
    return ForeignObjects(
        reservation_id=UUID(booked.json()["id"]),
        reservation_revision=booked.json()["revision"],
        queue_entry_id=UUID(joined.json()["id"]),
        queue_entry_revision=joined.json()["revision"],
        waitlist_entry_id=UUID(waitlisted.json()["id"]),
        waitlist_revision=waitlisted.json()["revision"],
        request_id=UUID(request_view["id"]),
        request_revision=request_view["revision"],
        reminder_plan_id=UUID(reminder.json()["id"]),
        reminder_revision=reminder.json()["revision"],
        actor_option_id=str(actor_slot["option_id"]),
    )


def _foreign_request(
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    name = operation.name
    if name == "capabilities.list":
        return "/v1/capabilities", {}, None, 200
    if name == "business.read":
        return "/v1/business", {}, None, 200
    if name == "catalog.offerings.list":
        return "/v1/catalog/offerings", {}, None, 200
    if name == "catalog.offerings.read":
        return f"/v1/catalog/offerings/{foreign.offering_key}", {}, None, 404
    if name == "appointments.find_slots":
        return (
            "/v1/appointments/slots",
            {
                "offering_version_id": str(foreign.offering_version_id),
                "window_start": "2030-01-07T13:00:00+00:00",
                "window_end": "2030-01-07T16:00:00+00:00",
            },
            None,
            404,
        )
    if name == "appointments.book":
        body: dict[str, object] = {
            "option_id": objects.actor_option_id,
            "subject_party_id": str(foreign.party_id),
        }
        return "/v1/appointments", {}, body, 422
    if name == "appointments.read":
        return f"/v1/appointments/{objects.reservation_id}", {}, None, 404
    if name == "appointments.cancel":
        return (
            f"/v1/appointments/{objects.reservation_id}/cancel",
            {},
            {"expected_revision": objects.reservation_revision, "reason": "cross tenant"},
            404,
        )
    if name == "appointments.reschedule":
        return (
            f"/v1/appointments/{objects.reservation_id}/reschedule",
            {},
            {
                "option_id": objects.actor_option_id,
                "expected_revision": objects.reservation_revision,
            },
            404,
        )
    if name == "appointments.attendance":
        return (
            f"/v1/appointments/{objects.reservation_id}/attendance",
            {},
            {"response": "accepted", "expected_revision": objects.reservation_revision},
            404,
        )
    if name == "queue.list":
        return "/v1/queues", {}, None, 200
    if name == "queue.join":
        return (
            f"/v1/queues/{actor.queue_id}/join",
            {},
            {"subject_party_id": str(foreign.party_id), "offering_id": str(actor.offering_id)},
            422,
        )
    if name == "queue.status":
        return (
            f"/v1/queues/{foreign.queue_id}/status",
            {"subject_party_id": str(actor.party_id)},
            None,
            404,
        )
    if name == "queue.leave":
        return (
            f"/v1/queues/{foreign.queue_id}/entries/{objects.queue_entry_id}/leave",
            {},
            {"expected_revision": objects.queue_entry_revision, "reason": "cross tenant"},
            404,
        )
    if name == "queue.call_next":
        return f"/v1/queues/{foreign.queue_id}/call-next", {}, None, 404
    if name == "waitlist.join":
        return (
            "/v1/waitlist",
            {},
            {"offering_id": str(actor.offering_id), "subject_party_id": str(foreign.party_id)},
            422,
        )
    if name == "waitlist.read":
        return f"/v1/waitlist/{objects.waitlist_entry_id}", {}, None, 404
    if name == "waitlist.leave":
        body = {"expected_revision": objects.waitlist_revision, "reason": "cross tenant"}
        return f"/v1/waitlist/{objects.waitlist_entry_id}/leave", {}, body, 404
    if name == "requests.submit":
        return (
            f"/v1/requests/definitions/{foreign.request_key}/submit",
            {},
            {"payload": {"message": "cross tenant"}},
            404,
        )
    if name == "requests.read":
        return f"/v1/requests/{objects.request_id}", {}, None, 404
    if name == "requests.cancel":
        body: dict[str, object] = {
            "reason": "cross tenant",
            "expected_revision": objects.request_revision,
        }
        return f"/v1/requests/{objects.request_id}/cancel", {}, body, 404
    if name == "reminders.create":
        return (
            "/v1/reminders",
            {},
            {
                "subject_party_id": str(foreign.party_id),
                "purpose": "medication_reminder",
                "timezone": "America/Santo_Domingo",
                "daily_times": ["08:00:00"],
                "channel_policy": {"channels": ["email"]},
                "template_key": "medication-reminder",
                "template_version": 1,
            },
            403,
        )
    if name == "reminders.read":
        return f"/v1/reminders/{objects.reminder_plan_id}", {}, None, 404
    if name == "reminders.cancel":
        return (
            f"/v1/reminders/{objects.reminder_plan_id}/cancel",
            {},
            {"expected_revision": objects.reminder_revision, "reason": "cross tenant"},
            404,
        )
    if name == "operational_copilot.interpret":
        return (
            "/v1/operational-copilot/interpret",
            {"text": f"propose recovery for queue {foreign.queue_id}"},
            None,
            200,
        )
    raise AssertionError(f"missing tenant probe for {name}")


async def _invoke(
    client: AsyncClient,
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[Response, int]:
    path, query, body, expected = _foreign_request(operation, actor, foreign, objects)
    key = f"cross-{operation.name}-{uuid4().hex}" if operation.idempotency_required else None
    headers = auth(actor, idempotency_key=key)
    response = await client.request(
        operation.method, path, params=query, json=body, headers=headers
    )
    return response, expected


def _test_id(operation: PublicHttpOperation) -> str:
    return operation.name


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", PUBLIC_HTTP_OPERATIONS, ids=_test_id)
async def test_every_public_operation_enforces_tenant_or_party_boundary_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "tenant-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "tenant-b")
    actors = {
        tenant_a.token: actor_for(tenant_a, allow_overrides=False),
        tenant_b.token: actor_for(tenant_b, allow_overrides=True),
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        objects = await _seed_foreign_objects(client, e2e_admin_conn, tenant_a, tenant_b)
        before = durable_snapshot(e2e_admin_conn)
        response, expected = await _invoke(client, operation, tenant_a, tenant_b, objects)
    assert response.status_code == expected, (operation.name, response.text)
    if operation.tenant_isolation in {TenantIsolationMode.FILTERED, TenantIsolationMode.CONTEXTUAL}:
        assert tenant_b.organization_key not in response.text
        assert tenant_b.display_name not in response.text
        assert tenant_b.offering_key not in response.text
        assert str(tenant_b.queue_id) not in response.text
    assert durable_snapshot(e2e_admin_conn) == before
