"""Business onboarding acceptance journey (docs/v3/44 section 9).

One newly provisioned organization (organization + bootstrap principal rows
only, the provisioning assumption) becomes fully operational using HTTP and
nothing else. Readiness transitions are observed on the real
`GET /v1/onboarding/readiness` report between the bootstrap, catalog, booking,
queue and communications steps, and every durable business claim is verified
against owner tables through the admin SQL connection — never from the HTTP
response alone. Only isolation is deliberately excluded; it is owned by the
dedicated cross-tenant isolation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from . import operational_support as support
from .tenant_sandbox import SandboxResolver

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract, pytest.mark.invariant]

_SIGNING_KEY = b"request-engine-onboarding-journey-key"
_TIMEZONE = "America/Santo_Domingo"

# The trusted onboarding-operator token: bootstrap/configuration capabilities
# plus the front-desk subject overrides the operator application uses to book
# and admit customers on their behalf.
OPERATOR_CAPABILITIES = frozenset(
    {
        "organization.bootstrap",
        "parties.register",
        "catalog.manage",
        "booking.manage_supply",
        "queue.configure",
        "communications.configure",
        "onboarding.read",
        "appointments.find_slots",
        "appointments.book",
        "appointments.subject_override",
        "queue.join",
        "queue.subject_override",
    }
)

_BOOTSTRAP_SCOPES = {
    "operations.manage_profile",
    "operations.manage_supply",
    "operations.manage_terms",
    "operations.manage_discovery",
}

# A Monday. Resource availability is Monday 09:00-12:00 local (UTC-4), so the
# bookable window is 13:00-16:00 UTC.
_SLOT_DAY_UTC = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)
_SLOT_DAY_END_UTC = datetime(2030, 1, 7, 16, 0, tzinfo=UTC)
_HOLIDAY = date(2030, 1, 28)


@dataclass(frozen=True, slots=True)
class ProvisionedTenant:
    organization_id: UUID
    principal_id: UUID
    token: str


def auth(tenant: ProvisionedTenant, *, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {tenant.token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _actor(tenant: ProvisionedTenant) -> ActorContext:
    return ActorContext(
        organization_id=tenant.organization_id,
        principal_id=tenant.principal_id,
        capabilities=OPERATOR_CAPABILITIES,
    )


def _public_client(e2e_session_factory: SessionFactory, tenant: ProvisionedTenant) -> AsyncClient:
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=SandboxResolver({tenant.token: _actor(tenant)}),
        appointment_option_signing_key=_SIGNING_KEY,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _operations_client(
    e2e_session_factory: SessionFactory, tenant: ProvisionedTenant
) -> AsyncClient:
    app = create_operational_app(
        session_factory=e2e_session_factory,
        actor_resolver=SandboxResolver({tenant.token: _actor(tenant)}),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _seed_provisioned_tenant(conn: support.PgConnection, prefix: str) -> ProvisionedTenant:
    suffix = uuid4().hex
    row = conn.execute(
        """
        WITH organization AS (
            INSERT INTO request_engine.organizations (organization_key, display_name)
            VALUES (%s, %s)
            RETURNING id
        ), principal AS (
            INSERT INTO request_engine.principals (
                organization_id, principal_kind, external_subject
            ) SELECT id, 'agent', %s FROM organization RETURNING organization_id, id
        )
        SELECT organization.id, principal.id FROM organization, principal
        """,
        (f"{prefix}-{suffix}", f"{prefix} {suffix[:10]}", f"bootstrap-{suffix}"),
    ).fetchone()
    assert row is not None
    return ProvisionedTenant(
        organization_id=cast(UUID, row[0]),
        principal_id=cast(UUID, row[1]),
        token=f"token-{suffix}",
    )


def _scalar(conn: support.PgConnection, query: LiteralString, params: tuple[object, ...]) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


async def _readiness(client: AsyncClient, tenant: ProvisionedTenant) -> dict[str, object]:
    response = await client.get("/v1/onboarding/readiness", headers=auth(tenant))
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


async def _register_organization_party(client: AsyncClient, tenant: ProvisionedTenant) -> UUID:
    response = await client.post(
        "/v1/parties",
        json={"party_kind": "organization", "display_name": "Clínica García RD"},
        headers=auth(tenant, idempotency_key=_key("party-org")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["party_id"]))


async def _bootstrap_authority(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, *, idempotency_key: str
) -> dict[str, object]:
    response = await client.post(
        "/v1/organization/bootstrap-operational-authority",
        json={"authority_party_id": str(party_id)},
        headers=auth(tenant, idempotency_key=idempotency_key),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


async def _set_location_hours(
    operations: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, location_id: UUID
) -> int:
    response = await operations.put(
        f"/v1/operations/locations/{location_id}/hours",
        json={
            "authority_party_id": str(party_id),
            "expected_operational_revision": 1,
            "windows": [
                {"weekday": weekday, "local_start": "08:00:00", "local_end": "17:00:00"}
                for weekday in range(5)
            ],
        },
        headers=auth(tenant, idempotency_key=_key("hours")),
    )
    assert response.status_code == 200, response.text
    revision = cast(int, response.json()["operational_revision"])
    assert revision > 1
    return revision


async def _declare_holiday(
    operations: AsyncClient, tenant: ProvisionedTenant, party_id: UUID
) -> None:
    response = await operations.put(
        "/v1/operations/organization/holidays",
        json={
            "authority_party_id": str(party_id),
            "holidays": [{"date": _HOLIDAY.isoformat(), "reason": "Día de la Restauración"}],
        },
        headers=auth(tenant, idempotency_key=_key("holidays")),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["locations_covered"] == 1
    assert body["exceptions_created"] == 1


async def _create_capability(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID
) -> UUID:
    response = await client.post(
        "/v1/catalog/resource-capabilities",
        json={
            "authority_party_id": str(party_id),
            "capability_key": f"cardiology-{uuid4().hex[:12]}",
            "display_name": "Cardiology consultation",
        },
        headers=auth(tenant, idempotency_key=_key("capability")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["capability_id"]))


async def _create_offering(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, capability_id: UUID
) -> tuple[UUID, UUID]:
    response = await client.post(
        "/v1/catalog/offerings",
        json={
            "authority_party_id": str(party_id),
            "offering_key": f"cardiology-consult-{uuid4().hex[:12]}",
            "display_name": "Cardiology consultation",
            "duration_minutes": 30,
            "bookable": True,
            "requirements": [{"capability_id": str(capability_id), "quantity": 1}],
        },
        headers=auth(tenant, idempotency_key=_key("offering")),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(cast(str, body["offering_id"])), UUID(cast(str, body["offering_version_id"]))


async def _set_booking_policy(
    client: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, offering_version_id: UUID
) -> None:
    response = await client.put(
        f"/v1/catalog/offerings/{offering_version_id}/booking-policy",
        json={
            "authority_party_id": str(party_id),
            "expected_revision": 0,
            "booking_policy": {
                "slot_step_minutes": 15,
                "attendance": {"no_show_after_minutes": 20},
                "communications": {"confirmation": False},
                "slot_recovery": {"enabled": False},
            },
        },
        headers=auth(tenant, idempotency_key=_key("booking-policy")),
    )
    assert response.status_code == 200, response.text
    assert response.json()["booking_policy_revision"] == 1


async def _set_booking_terms(
    operations: AsyncClient, tenant: ProvisionedTenant, party_id: UUID, offering_version_id: UUID
) -> None:
    response = await operations.put(
        f"/v1/operations/offering-versions/{offering_version_id}/booking-terms",
        json={
            "authority_party_id": str(party_id),
            "amount": "1500.00",
            "currency": "DOP",
        },
        headers=auth(tenant, idempotency_key=_key("booking-terms")),
    )
    assert response.status_code == 200, response.text


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
            "resource_key": f"dr-garcia-{uuid4().hex[:12]}",
            "display_name": "Dra. García",
            "capacity_model": "exclusive",
            "capability_ids": [str(capability_id)],
            "weekly_availability": [
                {"weekday": 0, "local_start": "09:00:00", "local_end": "12:00:00"}
            ],
        },
        headers=auth(tenant, idempotency_key=_key("resource")),
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
            "queue_key": f"walk-in-desk-{uuid4().hex[:12]}",
            "display_name": "Walk-in desk",
        },
        headers=auth(tenant, idempotency_key=_key("queue")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["queue_id"]))


async def _set_channel_policy(
    client: AsyncClient,
    tenant: ProvisionedTenant,
    party_id: UUID,
    purpose: str,
    *,
    enabled: bool,
    expected_revision: int,
) -> dict[str, object]:
    response = await client.put(
        f"/v1/communications/channel-policies/{purpose}",
        json={
            "authority_party_id": str(party_id),
            "enabled": enabled,
            "channels": ["whatsapp", "sms", "email"],
            "expected_revision": expected_revision,
        },
        headers=auth(tenant, idempotency_key=_key("channel-policy")),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return cast(dict[str, object], body)


async def _register_customer_party(client: AsyncClient, tenant: ProvisionedTenant) -> UUID:
    response = await client.post(
        "/v1/parties",
        json={"party_kind": "person", "display_name": "Pedro Martínez"},
        headers=auth(tenant, idempotency_key=_key("party-customer")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["party_id"]))


async def _find_slots(
    client: AsyncClient,
    tenant: ProvisionedTenant,
    offering_version_id: UUID,
    location_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, object]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(offering_version_id),
            "location_id": str(location_id),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        headers=auth(tenant),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return cast(list[dict[str, object]], body)


async def _book(
    client: AsyncClient, tenant: ProvisionedTenant, option_id: str, customer_party_id: UUID
) -> UUID:
    response = await client.post(
        "/v1/appointments",
        json={"option_id": option_id, "subject_party_id": str(customer_party_id)},
        headers=auth(tenant, idempotency_key=_key("book")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["id"]))


async def _join_queue(
    client: AsyncClient, tenant: ProvisionedTenant, queue_id: UUID, customer_party_id: UUID
) -> UUID:
    response = await client.post(
        f"/v1/queues/{queue_id}/join",
        json={"subject_party_id": str(customer_party_id)},
        headers=auth(tenant, idempotency_key=_key("queue-join")),
    )
    assert response.status_code == 201, response.text
    return UUID(cast(str, response.json()["id"]))


def _assert_bootstrap_grant(conn: support.PgConnection, tenant: ProvisionedTenant) -> None:
    rows = conn.execute(
        """
        SELECT scope_key, authority_kind, status
        FROM request_engine.representations
        WHERE organization_id = %s AND principal_id = %s
        """,
        (tenant.organization_id, tenant.principal_id),
    ).fetchall()
    assert {(row[0], row[1], row[2]) for row in rows} == {
        (scope_key, "delegated", "active") for scope_key in _BOOTSTRAP_SCOPES
    }


def _assert_policy_ledger_row(
    conn: support.PgConnection, tenant: ProvisionedTenant, offering_version_id: UUID
) -> None:
    row = conn.execute(
        """
        SELECT revision, booking_policy
        FROM request_engine.offering_version_booking_policies
        WHERE organization_id = %s AND offering_version_id = %s
        """,
        (tenant.organization_id, offering_version_id),
    ).fetchone()
    assert row is not None
    revision, policy = row
    assert revision == 1
    assert policy["slot_step_minutes"] == 15
    assert policy["attendance"]["no_show_after_minutes"] == 20


def _assert_booking_policy_ledger_is_append_only(
    conn: support.PgConnection, tenant: ProvisionedTenant, offering_version_id: UUID
) -> None:
    with pytest.raises(psycopg.Error) as excinfo:
        conn.execute(
            """
            UPDATE request_engine.offering_version_booking_policies
            SET booking_policy = booking_policy || '{"slot_step_minutes": 30}'::jsonb
            WHERE organization_id = %s AND offering_version_id = %s
            """,
            (tenant.organization_id, offering_version_id),
        )
    assert excinfo.value.sqlstate == "55000"


def _assert_reservation_commitment(
    conn: support.PgConnection,
    tenant: ProvisionedTenant,
    reservation_id: UUID,
    resource_id: UUID,
    expected_subject_party_id: UUID,
    option: dict[str, object],
) -> None:
    row = conn.execute(
        """
        SELECT status, subject_party_id, lower(during), upper(during), booking_policy_snapshot
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (tenant.organization_id, reservation_id),
    ).fetchone()
    assert row is not None
    status, subject_party_id, start_at, end_at, snapshot = row
    assert status == "confirmed"
    assert subject_party_id == expected_subject_party_id
    assert start_at == datetime.fromisoformat(cast(str, option["start_at"]))
    assert end_at == datetime.fromisoformat(cast(str, option["end_at"]))
    assert snapshot["slot_step_minutes"] == 15
    assert snapshot["attendance"]["no_show_after_minutes"] == 20

    claims = conn.execute(
        """
        SELECT resource_id, during, quantity, status
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (tenant.organization_id, reservation_id),
    ).fetchall()
    assert len(claims) == 1
    claim_resource_id, claim_during, quantity, claim_status = claims[0]
    assert claim_resource_id == resource_id
    assert claim_during.lower == start_at
    assert claim_during.upper == end_at
    assert quantity == 1
    assert claim_status == "active"


@pytest.mark.asyncio
async def test_newly_provisioned_organization_becomes_operational_through_http(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    tenant = _seed_provisioned_tenant(e2e_admin_conn, "onboarding-journey")

    async with (
        _public_client(e2e_session_factory, tenant) as client,
        _operations_client(e2e_session_factory, tenant) as operations,
    ):
        # 1. Empty world: every bootstrap blocker is visible.
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
        assert (
            _scalar(
                e2e_admin_conn,
                "SELECT count(*) FROM request_engine.parties "
                "WHERE organization_id = %s AND party_kind = 'organization'",
                (tenant.organization_id,),
            )
            == 0
        )

        # 2. Root business party + bootstrap authority.
        party_id = await _register_organization_party(client, tenant)
        bootstrap_key = _key("bootstrap")
        bootstrap = await _bootstrap_authority(
            client, tenant, party_id, idempotency_key=bootstrap_key
        )
        replay = await _bootstrap_authority(client, tenant, party_id, idempotency_key=bootstrap_key)
        assert replay == bootstrap
        assert set(cast(list[str], bootstrap["scope_keys"])) == _BOOTSTRAP_SCOPES
        _assert_bootstrap_grant(e2e_admin_conn, tenant)

        # 3. Location, operating hours and a declared national holiday closure.
        location_response = await operations.post(
            "/v1/operations/locations",
            json={
                "authority_party_id": str(party_id),
                "location_key": f"main-clinic-{uuid4().hex[:12]}",
                "display_name": "Main clinic",
                "timezone": _TIMEZONE,
            },
            headers=auth(tenant, idempotency_key=_key("location")),
        )
        assert location_response.status_code in {200, 201}, location_response.text
        location_id = UUID(cast(str, location_response.json()["location_id"]))
        assert location_response.json()["operational_revision"] == 1

        hours_revision = await _set_location_hours(operations, tenant, party_id, location_id)
        assert (
            _scalar(
                e2e_admin_conn,
                "SELECT operational_revision FROM request_engine.locations "
                "WHERE organization_id = %s AND id = %s",
                (tenant.organization_id, location_id),
            )
            == hours_revision
        )
        await _declare_holiday(operations, tenant, party_id)

        # Readiness after bootstrap + location: party and locations ready,
        # appointments still blocked without supply.
        report = await _readiness(client, tenant)
        assert report == {
            "business_party": {"ready": True},
            "locations": {"ready": True, "count": 1},
            "appointments": {
                "ready": False,
                "blockers": ["no_bookable_offering", "no_resource_supply"],
            },
            "walk_in_queue": {"ready": False, "queue_count": 0},
            "communications": {"ready": True, "blockers": []},
        }
        hours = e2e_admin_conn.execute(
            """
            SELECT weekday, local_start, local_end
            FROM request_engine.location_operational_hours
            WHERE organization_id = %s AND location_id = %s AND active
            ORDER BY weekday
            """,
            (tenant.organization_id, location_id),
        ).fetchall()
        assert len(hours) == 5
        assert all(row[0] == index for index, row in enumerate(hours))
        assert all(row[1] == time(8, 0) and row[2] == time(17, 0) for row in hours)

        local_tz = timezone(timedelta(hours=-4))
        holiday_row = e2e_admin_conn.execute(
            """
            SELECT exception_kind, lower(during), upper(during)
            FROM request_engine.location_hours_exceptions
            WHERE organization_id = %s AND location_id = %s AND active
            """,
            (tenant.organization_id, location_id),
        ).fetchone()
        assert holiday_row is not None
        assert holiday_row[0] == "unavailable"
        assert holiday_row[1] == datetime.combine(_HOLIDAY, time(0, 0), tzinfo=local_tz).astimezone(
            UTC
        )
        assert holiday_row[2] == datetime.combine(
            _HOLIDAY + timedelta(days=1), time(0, 0), tzinfo=local_tz
        ).astimezone(UTC)

        # 4. Catalog: capability, bookable offering + immutable version, and
        # a booking-policy override on the append-only ledger.
        capability_id = await _create_capability(client, tenant, party_id)
        replayed_capability = e2e_admin_conn.execute(
            "SELECT id FROM request_engine.resource_capabilities WHERE organization_id = %s",
            (tenant.organization_id,),
        ).fetchall()
        assert [row[0] for row in replayed_capability] == [capability_id]
        offering_id, offering_version_id = await _create_offering(
            client, tenant, party_id, capability_id
        )
        await _set_booking_policy(client, tenant, party_id, offering_version_id)
        await _set_booking_terms(operations, tenant, party_id, offering_version_id)
        _assert_policy_ledger_row(e2e_admin_conn, tenant, offering_version_id)
        _assert_booking_policy_ledger_is_append_only(e2e_admin_conn, tenant, offering_version_id)
        assert e2e_admin_conn.execute(
            "SELECT version, bookable FROM request_engine.offering_versions "
            "WHERE organization_id = %s AND id = %s",
            (tenant.organization_id, offering_version_id),
        ).fetchone() == (1, True)

        # 5. Supply: one exclusive resource with recurring weekly availability.
        resource_id = await _create_resource(client, tenant, party_id, location_id, capability_id)
        assert (
            _scalar(
                e2e_admin_conn,
                """
            SELECT count(*) FROM request_engine.resource_location_availability
            WHERE organization_id = %s
              AND resource_location_assignment_id = (
                  SELECT id FROM request_engine.resource_location_assignments
                  WHERE organization_id = %s AND resource_id = %s
                    AND upper(effective_during) IS NULL
              )
            """,
                (tenant.organization_id, tenant.organization_id, resource_id),
            )
            == 1
        )

        # Readiness after offering + resource: appointments ready.
        report = await _readiness(client, tenant)
        assert report == {
            "business_party": {"ready": True},
            "locations": {"ready": True, "count": 1},
            "appointments": {"ready": True, "blockers": []},
            "walk_in_queue": {"ready": False, "queue_count": 0},
            "communications": {"ready": True, "blockers": []},
        }

        # 6. Queue for walk-in flow.
        queue_id = await _create_queue(client, tenant, party_id, location_id, offering_id)
        report = await _readiness(client, tenant)
        assert report == {
            "business_party": {"ready": True},
            "locations": {"ready": True, "count": 1},
            "appointments": {"ready": True, "blockers": []},
            "walk_in_queue": {"ready": True, "queue_count": 1},
            "communications": {"ready": True, "blockers": []},
        }
        assert (
            _scalar(
                e2e_admin_conn,
                "SELECT count(*) FROM request_engine.service_queues "
                "WHERE organization_id = %s AND id = %s AND active "
                "AND location_id = %s AND offering_id = %s",
                (tenant.organization_id, queue_id, location_id, offering_id),
            )
            == 1
        )

        # 7. Communications channel policy: configure the confirmation
        # purpose, prove optimistic-revision rejection, then prove a
        # disabled purpose surfaces as the typed readiness blocker.
        policy = await _set_channel_policy(
            client,
            tenant,
            party_id,
            "appointment_confirmation",
            enabled=True,
            expected_revision=0,
        )
        assert policy["revision"] == 1
        stale = await client.put(
            "/v1/communications/channel-policies/appointment_confirmation",
            json={
                "authority_party_id": str(party_id),
                "enabled": True,
                "channels": ["whatsapp", "sms", "email"],
                "expected_revision": 0,
            },
            headers=auth(tenant, idempotency_key=_key("channel-policy-stale")),
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "revision_conflict"

        stored_policy = e2e_admin_conn.execute(
            """
            SELECT enabled, channel_policy->'channels'
            FROM request_engine.organization_channel_policies
            WHERE organization_id = %s AND purpose = 'appointment_confirmation'
            """,
            (tenant.organization_id,),
        ).fetchone()
        assert stored_policy is not None
        assert stored_policy[0] is True
        assert list(stored_policy[1]) == ["whatsapp", "sms", "email"]

        await _set_channel_policy(
            client,
            tenant,
            party_id,
            "appointment_reminder",
            enabled=False,
            expected_revision=0,
        )
        report = await _readiness(client, tenant)
        assert report["communications"] == {
            "ready": False,
            "blockers": ["channel_purpose_disabled"],
        }
        await _set_channel_policy(
            client,
            tenant,
            party_id,
            "appointment_reminder",
            enabled=True,
            expected_revision=1,
        )

        # 8. Customer, real slot discovery and booking.
        customer_party_id = await _register_customer_party(client, tenant)
        holiday_slots = await _find_slots(
            client,
            tenant,
            offering_version_id,
            location_id,
            datetime(2030, 1, 28, 13, 0, tzinfo=UTC),
            datetime(2030, 1, 28, 16, 0, tzinfo=UTC),
        )
        assert holiday_slots == []
        slots = await _find_slots(
            client,
            tenant,
            offering_version_id,
            location_id,
            _SLOT_DAY_UTC,
            _SLOT_DAY_END_UTC,
        )
        starts = [datetime.fromisoformat(cast(str, slot["start_at"])) for slot in slots]
        expected_starts = [_SLOT_DAY_UTC + timedelta(minutes=15 * index) for index in range(11)]
        assert starts == expected_starts
        option = slots[0]
        assert option["planned_duration_minutes"] == 30
        assert option["currency"] == "DOP"

        reservation_id = await _book(
            client, tenant, cast(str, option["option_id"]), customer_party_id
        )
        _assert_reservation_commitment(
            e2e_admin_conn, tenant, reservation_id, resource_id, customer_party_id, option
        )

        # 9. Walk-in queue admission.
        entry_id = await _join_queue(client, tenant, queue_id, customer_party_id)
        entry_row = e2e_admin_conn.execute(
            """
            SELECT status, subject_party_id, reservation_id
            FROM request_engine.queue_entries
            WHERE organization_id = %s AND id = %s
            """,
            (tenant.organization_id, entry_id),
        ).fetchone()
        assert entry_row is not None
        assert entry_row[0] == "waiting"
        assert entry_row[1] == customer_party_id
        assert entry_row[2] is None

        # 10. Final readiness: fully operational, no blockers.
        report = await _readiness(client, tenant)
        assert report == {
            "business_party": {"ready": True},
            "locations": {"ready": True, "count": 1},
            "appointments": {"ready": True, "blockers": []},
            "walk_in_queue": {"ready": True, "queue_count": 1},
            "communications": {"ready": True, "blockers": []},
        }
