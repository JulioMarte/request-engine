from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory

from .contextual_supply_support import contextualize_sandbox
from .discovery_runtime_support import discovery_client
from .discovery_seed_support import create_classification, publish_sandbox, search_body
from .f4_capacity_support import seed_today_schedule
from .f5_booking_fixture import five_minute_sandbox
from .operational_support import PgConnection, RuntimeCredentialsLike
from .tenant_sandbox import TenantSandbox, auth, seed_tenant_sandbox

BOGUS_OPTION = "discoopt_v1." + "0" * 64


def seed_requester_sandbox(conn: PgConnection) -> TenantSandbox:
    requester = five_minute_sandbox(conn, seed_tenant_sandbox(conn, "f5-cross-org-a"))
    seed_today_schedule(conn, requester)
    return requester


def seed_provider_sandbox(conn: PgConnection) -> tuple[TenantSandbox, str]:
    provider = seed_tenant_sandbox(conn, "f5-cross-org-b")
    contextualize_sandbox(conn, provider)
    classification_id, classification_key = create_classification(conn)
    publish_sandbox(conn, provider, classification_id, latitude=19.8000, longitude=-70.7000)
    return provider, classification_key


async def search_provider_option(
    conn: PgConnection,
    session_factory: SessionFactory,
    credentials: RuntimeCredentialsLike,
    provider: TenantSandbox,
    classification_key: str,
) -> str:
    async with discovery_client(conn, session_factory, credentials.database_url) as discovery:
        response = await discovery.post(
            "/v1/discovery/supply/search", json=search_body(classification_key)
        )
    assert response.status_code == 200, response.text
    options = cast(list[dict[str, Any]], response.json())
    selected = next(
        item for item in options if item["organization_key"] == provider.organization_key
    )
    option_id = cast(str, selected["option_id"])
    assert option_id.startswith("discoopt_v1.")
    return option_id


def replace_external_body(
    proposal: dict[str, Any],
    reservation_id: UUID,
    provider: TenantSandbox,
    option_id: str,
) -> dict[str, object]:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return {
        "expected_source_revision": checkpoint["recovery_source_revision"],
        "proposal_id": proposal["id"],
        "reservation_id": str(reservation_id),
        "expected_source_fingerprint": proposal["source_fingerprint"],
        "expected_proposal_fingerprint": proposal["proposal_fingerprint"],
        "allow_subject_override": False,
        "external_target": {
            "organization_id": str(provider.organization_id),
            "option_id": option_id,
            "subject_party_id": str(provider.party_id),
        },
    }


async def replace_external(
    client: AsyncClient,
    requester: TenantSandbox,
    *,
    incident_id: UUID,
    body: dict[str, object],
    idempotency_key: str,
) -> Any:
    return await client.post(
        f"/v1/operational-recovery/incidents/{incident_id}/replace-resource",
        json=body,
        headers=auth(requester, idempotency_key=idempotency_key),
    )


def assert_provider_commitment(
    conn: PgConnection, reservation_id: UUID, provider: TenantSandbox
) -> None:
    row = conn.execute(
        "SELECT organization_id, subject_party_id, status FROM request_engine.reservations "
        "WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row == (provider.organization_id, provider.party_id, "confirmed")
    consumed = conn.execute(
        "SELECT count(*) FROM request_engine.discovery_booking_handoffs "
        "WHERE consumed_reservation_id=%s",
        (reservation_id,),
    ).fetchone()
    assert consumed == (1,)
    commitment = conn.execute(
        "SELECT amount, currency, planned_duration_minutes FROM "
        "request_engine.reservation_commercial_commitments WHERE reservation_id=%s",
        (reservation_id,),
    ).fetchone()
    assert commitment == (4000.000000, "DOP", 45)
    claims = conn.execute(
        "SELECT count(*) FROM request_engine.capacity_claims "
        "WHERE reservation_id=%s AND status='active'",
        (reservation_id,),
    ).fetchone()
    assert claims == (1,)


def assert_source_disposal(conn: PgConnection, reservation_id: UUID) -> None:
    row = conn.execute(
        "SELECT status FROM request_engine.reservations WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None and row[0] == "cancelled"
    active = conn.execute(
        "SELECT count(*) FROM request_engine.capacity_claims "
        "WHERE reservation_id=%s AND status='active'",
        (reservation_id,),
    ).fetchone()
    assert active == (0,)
