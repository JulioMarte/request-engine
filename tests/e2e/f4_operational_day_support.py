from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient

from .f4_capacity_support import same_day_slots
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth


async def configure_projection(
    client: AsyncClient,
    sandbox: TenantSandbox,
) -> tuple[UUID, UUID]:
    expected = await client.post(
        "/v1/live-workloads",
        json={"workload_key": "scheduled", "display_name": "Scheduled"},
        headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
    )
    walk = await client.post(
        "/v1/live-workloads",
        json={"workload_key": "walk-in", "display_name": "Walk-in"},
        headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
    )
    assert expected.status_code == walk.status_code == 201
    expected_id = UUID(expected.json()["id"])
    walk_id = UUID(walk.json()["id"])
    scope = await client.post(
        "/v1/live-capacity/projection-policies",
        json={
            "service_queue_id": str(sandbox.queue_id),
            "resource_id": str(sandbox.resource_id),
            "location_id": str(sandbox.location_id),
        },
        headers=auth(sandbox, idempotency_key=f"scope-{uuid4().hex}"),
    )
    estimate = await client.post(
        "/v1/live-capacity/workload-estimate-policies",
        json={"workload_classification_id": str(walk_id), "duration_seconds": 1200},
        headers=auth(sandbox, idempotency_key=f"estimate-{uuid4().hex}"),
    )
    assert scope.status_code == estimate.status_code == 201
    return expected_id, walk_id


async def book_two_same_day(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> tuple[UUID, UUID]:
    reservations: list[UUID] = []
    for slot in (await same_day_slots(client, conn, sandbox))[:2]:
        booked = await client.post(
            "/v1/appointments",
            json={
                "option_id": str(slot["option_id"]),
                "subject_party_id": str(sandbox.party_id),
            },
            headers=auth(sandbox, idempotency_key=f"book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservations.append(UUID(booked.json()["id"]))
    return reservations[0], reservations[1]


async def read_projection(
    client: AsyncClient,
    sandbox: TenantSandbox,
) -> dict[str, Any]:
    response = await client.get(
        f"/v1/live-capacity/queues/{sandbox.queue_id}",
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def call_and_start(
    client: AsyncClient,
    sandbox: TenantSandbox,
    entry_id: UUID,
) -> dict[str, Any]:
    called = await client.post(
        f"/v1/queues/{sandbox.queue_id}/call-next",
        headers=auth(sandbox, idempotency_key=f"call-{uuid4().hex}"),
    )
    assert called.status_code == 200
    assert UUID(called.json()["id"]) == entry_id
    started = await client.post(
        f"/v1/queue-entries/{entry_id}/service/start",
        json={
            "resource_id": str(sandbox.resource_id),
            "location_id": str(sandbox.location_id),
            "expected_queue_revision": called.json()["revision"],
        },
        headers=auth(sandbox, idempotency_key=f"start-{uuid4().hex}"),
    )
    assert started.status_code == 201, started.text
    return started.json()
