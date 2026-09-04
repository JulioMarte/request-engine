"""Onboarding readiness report composition over real HTTP surfaces.

Three business-plausible worlds travel through the real public/operational HTTP
routes that exist for onboarding (Party registration, bootstrap authority,
locations, resource capabilities, offerings, resources and queues). Only the
provisioning prerequisite without any API (organization + principal rows) is
seeded by SQL, matching the tenant_sandbox convention. The report must reflect
owner-backed facts honestly: blockers only where the owning module has no
supply, and a communications blocker only for an intentionally disabled
purpose — never for an unconfigured default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from . import operational_support as support
from .tenant_sandbox import SandboxResolver

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


def auth(tenant: ProvisionedTenant, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {tenant.token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


ONBOARDING_CAPABILITIES = frozenset(
    {
        "parties.register",
        "organization.bootstrap",
        "catalog.manage",
        "booking.manage_supply",
        "queue.configure",
        "communications.configure",
        "onboarding.read",
    }
)

_SIGNING_KEY = b"request-engine-onboarding-readiness-key"


@dataclass(frozen=True, slots=True)
class ProvisionedTenant:
    organization_id: UUID
    principal_id: UUID
    token: str


def _actor(tenant: ProvisionedTenant) -> ActorContext:
    return ActorContext(
        organization_id=tenant.organization_id,
        principal_id=tenant.principal_id,
        capabilities=ONBOARDING_CAPABILITIES,
    )


def _uuid_row(
    conn: support.PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def seed_provisioned_tenant(conn: support.PgConnection, prefix: str) -> ProvisionedTenant:
    """Provisioning assumption: organization + principal exist, nothing else."""

    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{suffix}", f"{prefix} {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"bootstrap-{suffix}"),
    )
    return ProvisionedTenant(organization_id, principal_id, f"token-{suffix}")


def readiness_client(e2e_session_factory: SessionFactory, tenant: ProvisionedTenant) -> AsyncClient:
    app = _public_app(e2e_session_factory, tenant)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def operational_client(
    e2e_session_factory: SessionFactory, tenant: ProvisionedTenant
) -> AsyncClient:
    app = create_operational_app(
        session_factory=e2e_session_factory,
        actor_resolver=SandboxResolver({tenant.token: _actor(tenant)}),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _public_app(e2e_session_factory: SessionFactory, tenant: ProvisionedTenant):
    from request_engine.entrypoints.http.app import create_app

    return create_app(
        session_factory=e2e_session_factory,
        actor_resolver=SandboxResolver({tenant.token: _actor(tenant)}),
        appointment_option_signing_key=_SIGNING_KEY,
    )


async def _readiness(client: AsyncClient, tenant: ProvisionedTenant) -> dict[str, object]:
    response = await client.get("/v1/onboarding/readiness", headers=auth(tenant))
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


async def _register_business_party(client: AsyncClient, tenant: ProvisionedTenant) -> UUID:
    response = await client.post(
        "/v1/parties",
        json={"party_kind": "organization", "display_name": "Readiness Clinic"},
        headers=auth(tenant, idempotency_key=f"party-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["party_id"]))


async def _bootstrap_authority(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID
) -> None:
    response = await client.post(
        "/v1/organization/bootstrap-operational-authority",
        json={"authority_party_id": str(party_id)},
        headers=auth(tenant, idempotency_key=f"bootstrap-{uuid4().hex}"),
    )
    assert response.status_code == 200, response.text


async def _create_location(
    operations: AsyncClient, tenant: ProvisionedTenant, party_id: UUID
) -> UUID:
    response = await operations.post(
        "/v1/operations/locations",
        json={
            "authority_party_id": str(party_id),
            "location_key": f"location-{uuid4().hex[:12]}",
            "display_name": "Main clinic",
            "timezone": "America/Santo_Domingo",
        },
        headers=auth(tenant, idempotency_key=f"location-{uuid4().hex}"),
    )
    assert response.status_code in {200, 201}, response.text
    return UUID(cast(str, response.json()["location_id"]))


async def _create_capability_and_offering(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID
) -> UUID:
    capability = await client.post(
        "/v1/catalog/resource-capabilities",
        json={
            "authority_party_id": str(party_id),
            "capability_key": f"capability-{uuid4().hex[:12]}",
            "display_name": "Consultation",
        },
        headers=auth(tenant, idempotency_key=f"capability-{uuid4().hex}"),
    )
    assert capability.status_code == 201, capability.text
    capability_id = UUID(cast(str, capability.json()["capability_id"]))

    offering = await client.post(
        "/v1/catalog/offerings",
        json={
            "authority_party_id": str(party_id),
            "offering_key": f"offering-{uuid4().hex[:12]}",
            "display_name": "Cardiology consultation",
            "duration_minutes": 30,
            "bookable": True,
            "requirements": [{"capability_id": str(capability_id), "quantity": 1}],
        },
        headers=auth(tenant, idempotency_key=f"offering-{uuid4().hex}"),
    )
    assert offering.status_code == 201, offering.text
    return UUID(cast(str, offering.json()["offering_id"]))


async def _create_resource(
    client: AsyncClient,
    tenant: ProvisionedTenant,
    party_id: UUID,
    location_id: UUID,
    capability_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/booking/resources",
        json={
            "authority_party_id": str(party_id),
            "location_id": str(location_id),
            "resource_key": f"resource-{uuid4().hex[:12]}",
            "display_name": "Dr Garcia",
            "capability_ids": [str(capability_id)],
            "weekly_availability": [
                {"weekday": 0, "local_start": "09:00:00", "local_end": "12:00:00"}
            ],
        },
        headers=auth(tenant, idempotency_key=f"resource-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["resource_id"]))


async def _create_queue(
    client: AsyncClient,
    tenant: ProvisionedTenant,
    party_id: UUID,
    location_id: UUID,
    offering_id: UUID,
) -> UUID:
    response = await client.post(
        "/v1/queues",
        json={
            "authority_party_id": str(party_id),
            "location_id": str(location_id),
            "offering_id": str(offering_id),
            "queue_key": f"queue-{uuid4().hex[:12]}",
            "display_name": "Walk-in desk",
        },
        headers=auth(tenant, idempotency_key=f"queue-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["queue_id"]))


async def _set_channel_policy(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, *, enabled: bool, revision: int
) -> None:
    response = await client.put(
        "/v1/communications/channel-policies/appointment_confirmation",
        json={
            "authority_party_id": str(party_id),
            "enabled": enabled,
            "channels": ["whatsapp", "sms", "email"],
            "expected_revision": revision,
        },
        headers=auth(tenant, idempotency_key=f"channel-policy-{uuid4().hex}"),
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_empty_organization_reports_every_bootstrap_blocker(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_provisioned_tenant(e2e_admin_conn, "readiness-empty")
    async with readiness_client(e2e_session_factory, tenant) as client:
        report = await _readiness(client, tenant)

    assert report == {
        "business_party": {"ready": False},
        "locations": {"ready": False, "count": 0},
        "appointments": {
            "ready": False,
            "blockers": ["no_bookable_offering", "no_resource_supply"],
        },
        "walk_in_queue": {"ready": False, "queue_count": 0},
        "communications": {"ready": True, "blockers": []},
    }


@pytest.mark.asyncio
async def test_partial_organization_reports_only_remaining_blockers(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_provisioned_tenant(e2e_admin_conn, "readiness-partial")
    async with readiness_client(e2e_session_factory, tenant) as client:
        party_id = await _register_business_party(client, tenant)
        await _bootstrap_authority(client, tenant, party_id)
        async with operational_client(e2e_session_factory, tenant) as operations:
            location_id = await _create_location(operations, tenant, party_id)
            del location_id
            offering_id = await _create_capability_and_offering(client, tenant, party_id)
            del offering_id
        report = await _readiness(client, tenant)

    assert report == {
        "business_party": {"ready": True},
        "locations": {"ready": True, "count": 1},
        "appointments": {"ready": False, "blockers": ["no_resource_supply"]},
        "walk_in_queue": {"ready": False, "queue_count": 0},
        "communications": {"ready": True, "blockers": []},
    }


@pytest.mark.asyncio
async def test_complete_organization_has_no_blockers_and_disabled_purpose_blocks(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = seed_provisioned_tenant(e2e_admin_conn, "readiness-complete")
    async with readiness_client(e2e_session_factory, tenant) as client:
        party_id = await _register_business_party(client, tenant)
        await _bootstrap_authority(client, tenant, party_id)
        async with operational_client(e2e_session_factory, tenant) as operations:
            location_id = await _create_location(operations, tenant, party_id)
        capability = await client.post(
            "/v1/catalog/resource-capabilities",
            json={
                "authority_party_id": str(party_id),
                "capability_key": f"capability-{uuid4().hex[:12]}",
                "display_name": "Consultation",
            },
            headers=auth(tenant, idempotency_key=f"capability-{uuid4().hex}"),
        )
        assert capability.status_code == 201, capability.text
        capability_id = UUID(cast(str, capability.json()["capability_id"]))
        offering_id = await _create_capability_and_offering(client, tenant, party_id)
        await _create_resource(client, tenant, party_id, location_id, capability_id)
        queue_id = await _create_queue(client, tenant, party_id, location_id, offering_id)
        del queue_id

        baseline = await _readiness(client, tenant)
        assert baseline == {
            "business_party": {"ready": True},
            "locations": {"ready": True, "count": 1},
            "appointments": {"ready": True, "blockers": []},
            "walk_in_queue": {"ready": True, "queue_count": 1},
            "communications": {"ready": True, "blockers": []},
        }

        await _set_channel_policy(client, tenant, party_id, enabled=False, revision=0)
        disabled = await _readiness(client, tenant)
        assert disabled["communications"] == {
            "ready": False,
            "blockers": ["channel_purpose_disabled"],
        }

        await _set_channel_policy(client, tenant, party_id, enabled=True, revision=1)
        reenabled = await _readiness(client, tenant)
        assert reenabled["communications"] == {"ready": True, "blockers": []}
