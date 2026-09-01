from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    prepare_reconciliation,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from . import communication_reconcile_support as reconcile
from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_within_deadline_reconcile_still_proceeds(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, task_id, delivery_id = await reconcile.ambiguous_delivery(
        e2e_admin_conn,
        e2e_session_factory,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    async with tenant_transaction(e2e_session_factory, organization_id) as session:
        work = await prepare_reconciliation(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
        )

    assert work.kind is DeliveryWorkKind.LOOKUP
    assert work.lookup_request is not None
    assert work.lookup_request.delivery_id == delivery_id
    assert (
        reconcile.fetch_one(
            e2e_admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task_id,
        )
        == "delivering"
    )
    assert (
        reconcile.outbox_payloads(e2e_admin_conn, organization_id, "communication.task_failed.v1")
        == []
    )
