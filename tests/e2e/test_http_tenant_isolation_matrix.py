from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .evidence import durable_snapshot
from .http_isolation_probes import (
    ForeignObjects,
    isolation_actor,
)
from .http_isolation_probes import (
    foreign_request as _foreign_request,
)
from .http_surface import PublicHttpOperation, TenantIsolationMode
from .http_surface_current import MATRIX_OPERATIONS
from .tenant_sandbox import (
    TenantSandbox,
    auth,
    client_with_actors,
    first_slot,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


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
            "channel_policy": {"channels": ["email"], "provider_key": "provider-a"},
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


async def _invoke(
    client: AsyncClient,
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[Response, int]:
    path, query, body, expected = _foreign_request(operation, actor, foreign, objects)
    headers = auth(
        actor,
        idempotency_key=f"cross-{operation.name}-{uuid4().hex}"
        if operation.idempotency_required
        else None,
    )
    response = await client.request(
        operation.method, path, params=query, json=body, headers=headers
    )
    return response, expected


def _test_id(operation: PublicHttpOperation) -> str:
    return operation.name


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", MATRIX_OPERATIONS, ids=_test_id)
async def test_every_public_operation_enforces_tenant_or_party_boundary_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "tenant-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "tenant-b")
    actors = {
        tenant_a.token: isolation_actor(tenant_a, allow_overrides=False),
        tenant_b.token: isolation_actor(tenant_b, allow_overrides=True),
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
