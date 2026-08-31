from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pg_support as support
import pytest

from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import PermanentWorkError

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _lease_dispatch_action(
    conn: support.PgConnection,
    organization_id: UUID,
    communication_task_id: UUID,
) -> tuple[UUID, UUID]:
    claim_token = uuid4()
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at, status, claim_token, lease_until
        ) VALUES (
            %s, 'communications', 'dispatch_task', 1,
            'CommunicationTask', %s, %s::jsonb, %s,
            clock_timestamp(), clock_timestamp(), 'leased', %s,
            clock_timestamp() + interval '5 minutes'
        )
        RETURNING id
        """,
        (
            organization_id,
            communication_task_id,
            json.dumps({"communication_task_id": str(communication_task_id)}),
            f"module-action:{uuid4().hex}",
            claim_token,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0]), claim_token


@pytest.mark.asyncio
async def test_unusable_recipient_configuration_fails_task_durably_on_first_attempt(
    pg_admin_conn: support.PgConnection,
    pg_session_factory: SessionFactory,
) -> None:
    organization_id = support.new_org(pg_admin_conn, "config-poison")
    party_id = support.new_party(
        pg_admin_conn,
        organization_id,
        "Recipient without contact points",
    )
    task_id = support.new_task(
        pg_admin_conn,
        organization_id,
        party_id=party_id,
        contact_point_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    action_id, claim_token = _lease_dispatch_action(
        pg_admin_conn,
        organization_id,
        task_id,
    )
    lease = ScheduledActionLease(
        id=action_id,
        organization_id=organization_id,
        claim_token=claim_token,
        owner_module="communications",
        action_type="dispatch_task",
        action_version=1,
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(task_id)},
        attempt_count=0,
        lease_until=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduler = PostgresScheduledActionWorker(pg_session_factory)
    handler = CommunicationDeliveryScheduledHandler(pg_session_factory, scheduler, {})

    with pytest.raises(PermanentWorkError) as caught:
        await handler.handle(lease)

    assert caught.value.error_class == "delivery_configuration_invalid"
    assert (
        support.fetch_one(
            pg_admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task_id,
        )
        == "failed"
    )
    assert (
        support.fetch_one(
            pg_admin_conn,
            """
        SELECT count(*)
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
            UUID(str(task_id)),
        )
        == 0
    )
    failures = support.outbox_payloads(
        pg_admin_conn,
        organization_id,
        "communication.task_failed.v1",
    )
    assert len(failures) == 1
    assert failures[0]["communication_task_id"] == str(task_id)
    assert failures[0]["reason"] == "delivery_configuration_invalid"
