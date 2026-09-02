from uuid import UUID, uuid4

from httpx import AsyncClient

from . import operational_support as support
from .http_isolation_probe_flows_s0c import foreign_identifier
from .http_isolation_probes import ForeignObjects
from .tenant_sandbox import TenantSandbox, auth, first_slot


async def seed_foreign_objects(
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
    identifier = await client.post(
        f"/v1/parties/{foreign_tenant.party_id}/administrative-identifiers",
        json=foreign_identifier(),
        headers=auth(foreign_tenant, idempotency_key=f"foreign-admin-id-{uuid4().hex}"),
    )
    assert identifier.status_code == 201, identifier.text
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
