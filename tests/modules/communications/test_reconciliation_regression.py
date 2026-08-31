from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pg_support as support
import pytest
from reconcile_world import ambiguous_delivery

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    prepare_reconciliation,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


@pytest.mark.asyncio
async def test_within_deadline_reconcile_still_proceeds(
    pg_admin_conn: support.PgConnection,
    pg_session_factory: SessionFactory,
) -> None:
    organization_id, task_id, delivery_id = await ambiguous_delivery(
        pg_admin_conn,
        pg_session_factory,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    async with tenant_transaction(pg_session_factory, organization_id) as session:
        work = await prepare_reconciliation(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
        )

    assert work.kind is DeliveryWorkKind.LOOKUP
    assert work.lookup_request is not None
    assert work.lookup_request.delivery_id == delivery_id
    assert (
        support.fetch_one(
            pg_admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task_id,
        )
        == "delivering"
    )
    assert (
        support.outbox_payloads(pg_admin_conn, organization_id, "communication.task_failed.v1")
        == []
    )
