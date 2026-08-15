from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .evidence import durable_snapshot
from .http_surface import PUBLIC_HTTP_OPERATIONS, PublicHttpOperation, TenantIsolationMode
from .tenant_sandbox import TenantSandbox, auth, client_for, first_slot, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@dataclass(frozen=True, slots=True)
class ForeignObjects:
    reservation_id: UUID | None = None
    request_id: UUID | None = None


def _test_id(operation: PublicHttpOperation) -> str:
    return operation.name


async def _create_foreign_objects(
    client: AsyncClient,
    tenant: TenantSandbox,
    operation: PublicHttpOperation,
) -> ForeignObjects:
    reservation_id: UUID | None = None
    request_id: UUID | None = None

    if operation.name in {
        "booking.appointments.read",
        "booking.appointments.cancel",
        "booking.appointments.reschedule",
    }:
        slot = await first_slot(client, tenant)
        response = await client.post(
            "/v1/appointments",
            json={
                "offering_version_id": str(tenant.offering_version_id),
                "subject_party_id": str(tenant.party_id),
                "location_id": str(tenant.location_id),
                "start_at": slot["start_at"],
                "resources": slot["resources"],
            },
            headers=auth(tenant, idempotency_key=f"foreign-book-{uuid4().hex}"),
        )
        assert response.status_code == 201, response.text
        reservation_id = UUID(response.json()["id"])

    if operation.name in {
        "requests.read",
        "requests.record_result",
        "requests.complete",
        "requests.cancel",
        "requests.fail",
    }:
        response = await client.post(
            f"/v1/requests/definitions/{tenant.request_key}/submit",
            json={
                "payload": {"message": "foreign tenant request"},
                "requester_party_id": str(tenant.party_id),
            },
            headers=auth(tenant, idempotency_key=f"foreign-request-{uuid4().hex}"),
        )
        assert response.status_code == 201, response.text
        request_id = UUID(response.json()["request"]["id"])

    return ForeignObjects(reservation_id=reservation_id, request_id=request_id)


def _foreign_request(
    operation: PublicHttpOperation,
    actor_tenant: TenantSandbox,
    foreign_tenant: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None]:
    name = operation.name

    if name == "business.read":
        return "/v1/business", {}, None
    if name == "catalog.offerings.list":
        return "/v1/catalog/offerings", {}, None
    if name == "catalog.offerings.read":
        return f"/v1/catalog/offerings/{foreign_tenant.offering_key}", {}, None
    if name == "booking.slots.find":
        return (
            "/v1/appointments/slots",
            {
                "offering_version_id": str(foreign_tenant.offering_version_id),
                "location_id": str(foreign_tenant.location_id),
                "window_start": "2030-01-07T13:00:00+00:00",
                "window_end": "2030-01-07T16:00:00+00:00",
            },
            None,
        )
    if name == "booking.appointments.book":
        return (
            "/v1/appointments",
            {},
            {
                "offering_version_id": str(foreign_tenant.offering_version_id),
                "subject_party_id": str(foreign_tenant.party_id),
                "location_id": str(foreign_tenant.location_id),
                "start_at": "2030-01-07T13:00:00+00:00",
                "resources": [
                    {
                        "requirement_id": str(foreign_tenant.requirement_id),
                        "resource_id": str(foreign_tenant.resource_id),
                    }
                ],
            },
        )
    if name == "booking.appointments.read":
        assert objects.reservation_id is not None
        return f"/v1/appointments/{objects.reservation_id}", {}, None
    if name == "booking.appointments.cancel":
        assert objects.reservation_id is not None
        return (
            f"/v1/appointments/{objects.reservation_id}/cancel",
            {},
            {"reason": "cross-tenant probe"},
        )
    if name == "booking.appointments.reschedule":
        assert objects.reservation_id is not None
        return (
            f"/v1/appointments/{objects.reservation_id}/reschedule",
            {},
            {
                "start_at": "2030-01-07T14:00:00+00:00",
                "location_id": str(foreign_tenant.location_id),
                "resources": [
                    {
                        "requirement_id": str(foreign_tenant.requirement_id),
                        "resource_id": str(foreign_tenant.resource_id),
                    }
                ],
            },
        )
    if name == "queue.list":
        return "/v1/queues", {}, None
    if name == "queue.join":
        return (
            f"/v1/queues/{foreign_tenant.queue_id}/join",
            {},
            {"subject_party_id": str(actor_tenant.party_id)},
        )
    if name == "queue.status":
        return (
            f"/v1/queues/{foreign_tenant.queue_id}/status",
            {"subject_party_id": str(actor_tenant.party_id)},
            None,
        )
    if name == "queue.leave":
        return (
            f"/v1/queues/{foreign_tenant.queue_id}/leave",
            {},
            {
                "subject_party_id": str(actor_tenant.party_id),
                "reason": "cross-tenant probe",
            },
        )
    if name == "queue.call_next":
        return f"/v1/queues/{foreign_tenant.queue_id}/call-next", {}, None
    if name == "requests.submit":
        return (
            f"/v1/requests/definitions/{foreign_tenant.request_key}/submit",
            {},
            {"payload": {"message": "cross-tenant probe"}},
        )
    if name.startswith("requests."):
        assert objects.request_id is not None
        base = f"/v1/requests/{objects.request_id}"
        if name == "requests.read":
            return base, {}, None
        if name == "requests.record_result":
            return (
                f"{base}/result",
                {},
                {"result_payload": {"accepted": True}, "expected_revision": 1},
            )
        if name == "requests.complete":
            return (
                f"{base}/complete",
                {},
                {"result_payload": {"accepted": True}, "expected_revision": 1},
            )
        if name == "requests.cancel":
            return (
                f"{base}/cancel",
                {},
                {"reason": "cross-tenant probe", "expected_revision": 1},
            )
        if name == "requests.fail":
            return (
                f"{base}/fail",
                {},
                {"error_class": "cross_tenant_probe", "details": {}, "expected_revision": 1},
            )

    raise AssertionError(f"tenant probe is not implemented for {name}")


async def _invoke_foreign_probe(
    client: AsyncClient,
    operation: PublicHttpOperation,
    actor_tenant: TenantSandbox,
    foreign_tenant: TenantSandbox,
    objects: ForeignObjects,
) -> Response:
    path, query, body = _foreign_request(operation, actor_tenant, foreign_tenant, objects)
    headers = auth(
        actor_tenant,
        idempotency_key=(
            f"cross-tenant-{operation.name}-{uuid4().hex}"
            if operation.idempotency_required
            else None
        ),
    )
    return await client.request(
        operation.method,
        path,
        params=query,
        json=body,
        headers=headers,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", PUBLIC_HTTP_OPERATIONS, ids=_test_id)
async def test_every_public_operation_enforces_declared_tenant_isolation_without_mutation(
    operation: PublicHttpOperation,
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant_a = seed_tenant_sandbox(e2e_admin_conn, "tenant-a")
    tenant_b = seed_tenant_sandbox(e2e_admin_conn, "tenant-b")

    async with client_for(e2e_session_factory, tenant_a, tenant_b) as client:
        objects = await _create_foreign_objects(client, tenant_b, operation)
        before = durable_snapshot(e2e_admin_conn)
        response = await _invoke_foreign_probe(
            client,
            operation,
            tenant_a,
            tenant_b,
            objects,
        )

    if operation.tenant_isolation is TenantIsolationMode.FILTERED:
        assert response.status_code == 200, (operation.name, response.text)
        assert tenant_b.organization_key not in response.text
        assert tenant_b.display_name not in response.text
        assert tenant_b.offering_key not in response.text
        assert str(tenant_b.queue_id) not in response.text
    else:
        assert operation.tenant_isolation is TenantIsolationMode.NOT_FOUND
        assert response.status_code == 404, (operation.name, response.text)

    assert durable_snapshot(e2e_admin_conn) == before
