from typing import cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .evidence import durable_snapshot
from .front_desk_recall_support import (
    DayBoardPayload,
    StaffRecallPayload,
    TriageResultPayload,
    book_and_check_in,
    day_params,
    front_desk_actor,
)
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_human_front_desk_hold_refresh_release_journey(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "front-desk-human")
    async with client_with_actors(
        e2e_session_factory, {sandbox.token: front_desk_actor(sandbox)}
    ) as client:
        reservation, entry = await book_and_check_in(client, sandbox)
        before = await client.get(
            "/v1/appointments/day-board", params=day_params(sandbox), headers=auth(sandbox)
        )
        before_items = cast(list[DayBoardPayload], before.json())
        assert before.status_code == 200 and before_items[0]["recall_eligible"] is True
        key = f"hold-{uuid4().hex}"
        body: dict[str, str | int] = {
            "condition_kind": "until_event",
            "event_key": "external_step_completed",
            "reason": "waiting for external prerequisite",
            "expected_revision": entry["revision"],
        }
        url = f"/v1/queue-entries/{entry['id']}/recall-hold"
        held = await client.post(url, json=body, headers=auth(sandbox, idempotency_key=key))
        replay = await client.post(url, json=body, headers=auth(sandbox, idempotency_key=key))
        held_payload = cast(TriageResultPayload, held.json())
        replay_payload = cast(TriageResultPayload, replay.json())
        assert held.status_code == replay.status_code == 200
        assert replay_payload == held_payload
        hold = held_payload["hold"]
        assert hold is not None
        staff = await client.get(f"/v1/queues/{sandbox.queue_id}/staff", headers=auth(sandbox))
        board = await client.get(
            "/v1/appointments/day-board", params=day_params(sandbox), headers=auth(sandbox)
        )
        staff_items = cast(list[StaffRecallPayload], staff.json())
        board_items = cast(list[DayBoardPayload], board.json())
        assert staff_items[0]["recall_eligible"] is False
        assert board_items[0]["reservation_id"] == reservation["id"]
        assert board_items[0]["recall_hold_id"] == hold["id"]
        release_body: dict[str, str | int] = {
            "hold_id": hold["id"],
            "expected_revision": held_payload["revision"],
        }
        released = await client.post(
            f"{url}/release",
            json=release_body,
            headers=auth(sandbox, idempotency_key=f"release-{uuid4().hex}"),
        )
        assert released.status_code == 200
        refreshed = await client.get(
            "/v1/appointments/day-board", params=day_params(sandbox), headers=auth(sandbox)
        )
        refreshed_items = cast(list[DayBoardPayload], refreshed.json())
        assert refreshed_items[0]["recall_eligible"] is True
        assert refreshed_items[0]["recall_hold_id"] is None


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_bot_retry_stale_ui_and_capability_rejection_are_fail_closed(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "front-desk-bot")
    read_only_token = f"read-only-{uuid4().hex}"
    read_only = ActorContext(
        sandbox.organization_id,
        sandbox.principal_id,
        frozenset({"appointments.day_board", "queue.staff_read"}),
    )
    actors = {sandbox.token: front_desk_actor(sandbox), read_only_token: read_only}
    async with client_with_actors(e2e_session_factory, actors) as client:
        _, entry = await book_and_check_in(client, sandbox)
        key = f"bot-hold-{uuid4().hex}"
        url = f"/v1/queue-entries/{entry['id']}/recall-hold"
        body: dict[str, str | int] = {
            "condition_kind": "until_customer_initiates",
            "expected_revision": entry["revision"],
            "reason": "bot could not reach customer",
        }
        held = await client.post(url, json=body, headers=auth(sandbox, idempotency_key=key))
        assert held.status_code == 200
        held_payload = cast(TriageResultPayload, held.json())
        hold = held_payload["hold"]
        assert hold is not None
        before_rejections = durable_snapshot(e2e_admin_conn)
        stale_body: dict[str, str | int] = {
            "hold_id": hold["id"],
            "expected_revision": entry["revision"],
        }
        stale = await client.post(
            f"{url}/release",
            json=stale_body,
            headers=auth(sandbox, idempotency_key=f"stale-{uuid4().hex}"),
        )
        release_body: dict[str, str | int] = {
            "hold_id": hold["id"],
            "expected_revision": held_payload["revision"],
        }
        denied = await client.post(
            f"{url}/release",
            json=release_body,
            headers={"Authorization": f"Bearer {read_only_token}", "Idempotency-Key": "denied"},
        )
        conflict_body: dict[str, str | int] = {
            **body,
            "expected_revision": held_payload["revision"],
            "reason": "different retry payload",
        }
        conflict = await client.post(
            url,
            json=conflict_body,
            headers=auth(sandbox, idempotency_key=key),
        )
        assert stale.status_code == 409
        assert denied.status_code == 403
        assert conflict.status_code == 409
        assert durable_snapshot(e2e_admin_conn) == before_rejections
        visible = await client.get(
            f"/v1/queues/{sandbox.queue_id}/staff",
            headers={"Authorization": f"Bearer {read_only_token}"},
        )
        visible_items = cast(list[StaffRecallPayload], visible.json())
        assert visible.status_code == 200
        assert visible_items[0]["recall_hold_id"] == hold["id"]
