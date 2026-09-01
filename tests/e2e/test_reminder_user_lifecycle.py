from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import auth, client_for, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.contract
async def test_reminder_create_read_cancel_replay_cancels_future_work(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "reminder-lifecycle")
    create_key = f"reminder-create-{uuid4().hex}"
    create_body = {
        "subject_party_id": str(sandbox.party_id),
        "purpose": "medication",
        "timezone": "America/Santo_Domingo",
        "daily_times": ["09:00:00", "21:00:00"],
        "max_lateness_minutes": 45,
        "channel_policy": {"channels": ["whatsapp"]},
        "template_key": "medication-reminder",
        "template_version": 1,
    }

    async with client_for(e2e_session_factory, sandbox) as client:
        created = await client.post(
            "/v1/reminders",
            headers=auth(sandbox, idempotency_key=create_key),
            json=create_body,
        )
        replay = await client.post(
            "/v1/reminders",
            headers=auth(sandbox, idempotency_key=create_key),
            json=create_body,
        )
        assert created.status_code == 201, created.text
        assert replay.status_code == 201, replay.text
        assert replay.json() == created.json()
        plan = created.json()
        plan_id = UUID(plan["id"])

        read = await client.get(f"/v1/reminders/{plan_id}", headers=auth(sandbox))
        assert read.status_code == 200
        assert read.json() == plan

        cancel_key = f"reminder-cancel-{uuid4().hex}"
        cancel_body = {"expected_revision": plan["revision"], "reason": "no longer needed"}
        cancelled = await client.post(
            f"/v1/reminders/{plan_id}/cancel",
            headers=auth(sandbox, idempotency_key=cancel_key),
            json=cancel_body,
        )
        cancel_replay = await client.post(
            f"/v1/reminders/{plan_id}/cancel",
            headers=auth(sandbox, idempotency_key=cancel_key),
            json=cancel_body,
        )

    assert cancelled.status_code == 200, cancelled.text
    assert cancel_replay.json() == cancelled.json()
    assert cancelled.json()["status"] == "cancelled"
    row = e2e_admin_conn.execute(
        "SELECT status, revision FROM request_engine.reminder_plans WHERE id = %s",
        (plan_id,),
    ).fetchone()
    assert row == ("cancelled", plan["revision"] + 1)
    pending = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions "
        "WHERE subject_kind = 'ReminderPlan' AND subject_id = %s AND status = 'pending'",
        (plan_id,),
    ).fetchone()
    assert pending == (0,)
