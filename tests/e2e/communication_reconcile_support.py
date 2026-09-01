from __future__ import annotations

import json
from datetime import datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from . import operational_support as support

CHANNEL_POLICY = {
    "channels": ["email"],
    "provider_key": "provider-a",
    "reconcile_after_seconds": 30,
    "retry_after_seconds": 30,
}


def new_task(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    party_id: UUID,
    contact_point_id: UUID | None,
    expires_at: datetime,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status, expires_at
        ) VALUES (
            %s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, 'pending', %s
        )
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_point_id,
            json.dumps(CHANNEL_POLICY),
            f"module-task:{uuid4().hex}",
            expires_at,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def fetch_one(conn: support.PgConnection, query: LiteralString, *params: Any) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def outbox_payloads(
    conn: support.PgConnection,
    organization_id: UUID,
    event_type: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT payload
        FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = %s
        ORDER BY created_at, id
        """,
        (organization_id, event_type),
    ).fetchall()
    return [cast(dict[str, object], row[0]) for row in rows]


async def ambiguous_delivery(
    conn: support.PgConnection,
    session_factory: SessionFactory,
    *,
    expires_at: datetime,
) -> tuple[UUID, UUID, UUID]:
    organization_id = support.new_org(conn, "reconcile-deadline")
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_point_id = support.new_contact_point(
        conn,
        organization_id,
        party_id,
        "reconcile-deadline",
    )
    task_id = new_task(
        conn,
        organization_id,
        party_id=party_id,
        contact_point_id=contact_point_id,
        expires_at=expires_at,
    )
    async with tenant_transaction(session_factory, organization_id) as session:
        prepared = await prepare_dispatch(
            session,
            organization_id=organization_id,
            communication_task_id=task_id,
        )
    assert prepared.kind is DeliveryWorkKind.SEND
    assert prepared.delivery_id is not None
    delivery_id = prepared.delivery_id
    async with tenant_transaction(session_factory, organization_id) as session:
        await finalize_provider_result(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
            result=ProviderDeliveryResult(
                status=ProviderDeliveryStatus.AMBIGUOUS,
                retryable=False,
                result_data={"source": "reconcile-deadline-test"},
            ),
        )
    return organization_id, task_id, delivery_id
