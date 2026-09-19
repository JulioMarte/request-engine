"""HTTP builders for the operational booking world reused by booking E2E journeys.

The step bodies mirror the accepted onboarding journey so the resulting world is
configuration-identical: one location with weekday hours and one holiday, one
resource capability, one bookable offering with slot step 15 and terms, and one
exclusive resource available Monday 09:00-12:00 local (UTC-4), which makes
13:00-16:00 UTC the deterministic bookable window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID, uuid4

from httpx import AsyncClient

from .native_provisioning_support import tenant_headers

TIMEZONE = "America/Santo_Domingo"
SLOT_DAY_UTC = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)
SLOT_DAY_END_UTC = datetime(2030, 1, 7, 16, 0, tzinfo=UTC)
_HOLIDAY = date(2030, 1, 28)


@dataclass(frozen=True, slots=True)
class BookableWorld:
    organization_party_id: UUID
    location_id: UUID
    capability_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    resource_id: UUID


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


async def register_organization_party(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/parties",
        json={"party_kind": "organization", "display_name": "Clínica García RD"},
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("party-org")
        ),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["party_id"]))


async def bootstrap_operational_authority(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
) -> dict[str, object]:
    response = await client.post(
        "/v1/organization/bootstrap-operational-authority",
        json={"authority_party_id": str(authority_party_id)},
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("bootstrap")
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


async def create_location(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/operations/locations",
        json={
            "authority_party_id": str(authority_party_id),
            "location_key": f"main-clinic-{uuid4().hex[:12]}",
            "display_name": "Main clinic",
            "timezone": TIMEZONE,
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("location")
        ),
    )
    assert response.status_code in {200, 201}, response.text
    assert response.json()["operational_revision"] == 1
    return UUID(cast(str, response.json()["location_id"]))


async def set_location_hours(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
    location_id: UUID,
) -> None:
    response = await client.put(
        f"/v1/operations/locations/{location_id}/hours",
        json={
            "authority_party_id": str(authority_party_id),
            "expected_operational_revision": 1,
            "windows": [
                {"weekday": weekday, "local_start": "08:00:00", "local_end": "17:00:00"}
                for weekday in range(5)
            ],
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("hours")
        ),
    )
    assert response.status_code == 200, response.text
    assert cast(int, response.json()["operational_revision"]) > 1


async def declare_holiday(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
) -> None:
    response = await client.put(
        "/v1/operations/organization/holidays",
        json={
            "authority_party_id": str(authority_party_id),
            "holidays": [{"date": _HOLIDAY.isoformat(), "reason": "Día de la Restauración"}],
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("holidays")
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["locations_covered"] == 1
    assert body["exceptions_created"] == 1


async def create_resource_capability(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/catalog/resource-capabilities",
        json={
            "authority_party_id": str(authority_party_id),
            "capability_key": f"cardiology-{uuid4().hex[:12]}",
            "display_name": "Cardiology consultation",
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("capability")
        ),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["capability_id"]))


async def create_offering(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
    capability_id: UUID,
) -> tuple[UUID, UUID]:
    response = await client.post(
        "/v1/catalog/offerings",
        json={
            "authority_party_id": str(authority_party_id),
            "offering_key": f"cardiology-consult-{uuid4().hex[:12]}",
            "display_name": "Cardiology consultation",
            "duration_minutes": 30,
            "bookable": True,
            "requirements": [{"capability_id": str(capability_id), "quantity": 1}],
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("offering")
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(cast(str, body["offering_id"])), UUID(cast(str, body["offering_version_id"]))


async def set_booking_policy(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
    offering_version_id: UUID,
) -> None:
    response = await client.put(
        f"/v1/catalog/offerings/{offering_version_id}/booking-policy",
        json={
            "authority_party_id": str(authority_party_id),
            "expected_revision": 0,
            "booking_policy": {
                "slot_step_minutes": 15,
                "attendance": {"no_show_after_minutes": 20},
                "communications": {"confirmation": False},
                "slot_recovery": {"enabled": False},
            },
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("booking-policy")
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["booking_policy_revision"] == 1


async def set_booking_terms(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
    offering_version_id: UUID,
) -> None:
    response = await client.put(
        f"/v1/operations/offering-versions/{offering_version_id}/booking-terms",
        json={
            "authority_party_id": str(authority_party_id),
            "amount": "1500.00",
            "currency": "DOP",
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("booking-terms")
        ),
    )
    assert response.status_code == 200, response.text


async def create_resource(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    authority_party_id: UUID,
    location_id: UUID,
    capability_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/booking/resources",
        json={
            "authority_party_id": str(authority_party_id),
            "location_id": str(location_id),
            "resource_key": f"dr-garcia-{uuid4().hex[:12]}",
            "display_name": "Dra. García",
            "capacity_model": "exclusive",
            "capability_ids": [str(capability_id)],
            "weekly_availability": [
                {"weekday": 0, "local_start": "09:00:00", "local_end": "12:00:00"}
            ],
        },
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("resource")
        ),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["resource_id"]))


async def build_bookable_world(
    client: AsyncClient,
    operations_client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
) -> BookableWorld:
    organization_party_id = await register_organization_party(
        client, token=token, organization_id=organization_id
    )
    await bootstrap_operational_authority(
        client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
    )
    location_id = await create_location(
        operations_client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
    )
    await set_location_hours(
        operations_client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
        location_id=location_id,
    )
    await declare_holiday(
        operations_client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
    )
    capability_id = await create_resource_capability(
        client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
    )
    offering_id, offering_version_id = await create_offering(
        client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
        capability_id=capability_id,
    )
    await set_booking_policy(
        client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
        offering_version_id=offering_version_id,
    )
    await set_booking_terms(
        operations_client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
        offering_version_id=offering_version_id,
    )
    resource_id = await create_resource(
        client,
        token=token,
        organization_id=organization_id,
        authority_party_id=organization_party_id,
        location_id=location_id,
        capability_id=capability_id,
    )
    return BookableWorld(
        organization_party_id=organization_party_id,
        location_id=location_id,
        capability_id=capability_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        resource_id=resource_id,
    )


async def find_slots(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    offering_version_id: UUID,
    location_id: UUID,
) -> list[dict[str, object]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(offering_version_id),
            "location_id": str(location_id),
            "window_start": SLOT_DAY_UTC.isoformat(),
            "window_end": SLOT_DAY_END_UTC.isoformat(),
        },
        headers=tenant_headers(token=token, organization_id=organization_id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return cast(list[dict[str, object]], body)


async def book_appointment(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    option_id: str,
    subject_party_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/appointments",
        json={"option_id": option_id, "subject_party_id": str(subject_party_id)},
        headers=tenant_headers(
            token=token, organization_id=organization_id, idempotency_key=_key("book")
        ),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["id"]))
