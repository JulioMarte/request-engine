from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pg_support as support

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


async def ambiguous_delivery(
    conn: support.PgConnection,
    session_factory: SessionFactory,
    *,
    expires_at: datetime,
) -> tuple[UUID, UUID, UUID]:
    organization_id = support.new_org(conn, "reconcile-deadline")
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_point_id = support.new_contact_point(conn, organization_id, party_id)
    task_id = support.new_task(
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
