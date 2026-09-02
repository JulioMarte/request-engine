from dataclasses import replace
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from . import operational_support as support
from .tenant_sandbox import (
    actor_for,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_F7E_CAPABILITIES = frozenset(
    {
        "queue.operator_select",
        "queue.recall_hold",
        "queue.release_recall_hold",
        "queue.skip",
    }
)


@pytest.mark.asyncio
async def test_f7e_same_day_selection_http_journey_reaches_postgres_owner(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f7e-http")
    base_actor = actor_for(sandbox)
    actor = replace(base_actor, capabilities=base_actor.capabilities | _F7E_CAPABILITIES)

    async with client_with_actors(e2e_session_factory, {sandbox.token: actor}) as client:
        joined = await client.post(
            f"/v1/queues/{sandbox.queue_id}/join",
            json={"subject_party_id": str(sandbox.party_id)},
            headers=auth(sandbox, idempotency_key=f"f7e-join-{uuid4().hex}"),
        )
        assert joined.status_code == 201, joined.text
        entry = joined.json()

        skipped = await client.post(
            f"/v1/queues/{sandbox.queue_id}/skip",
            json={"reason": "no_response"},
            headers=auth(sandbox, idempotency_key=f"f7e-skip-{uuid4().hex}"),
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json() == {"skipped_entry_id": entry["id"], "called_entry": None}

        held = await client.post(
            f"/v1/queues/{sandbox.queue_id}/entries/{entry['id']}/recall-hold",
            json={
                "expected_revision": entry["revision"],
                "kind": "until_customer_initiates",
                "release_at": None,
                "reason": "stepped_away",
            },
            headers=auth(sandbox, idempotency_key=f"f7e-hold-{uuid4().hex}"),
        )
        assert held.status_code == 200, held.text
        hold = held.json()
        assert hold["queue_entry_id"] == entry["id"]
        assert hold["reason"] == "stepped_away"

        released = await client.post(
            f"/v1/queues/{sandbox.queue_id}/entries/{entry['id']}/recall-hold/release",
            json={
                "hold_id": hold["id"],
                "expected_revision": hold["queue_entry_revision"],
            },
            headers=auth(sandbox, idempotency_key=f"f7e-release-{uuid4().hex}"),
        )
        assert released.status_code == 200, released.text
        released_hold = released.json()
        assert released_hold["id"] == hold["id"]
        assert released_hold["released_at"] is not None

        selected = await client.post(
            f"/v1/queues/{sandbox.queue_id}/entries/{entry['id']}/operator-select",
            json={
                "expected_revision": released_hold["queue_entry_revision"],
                "reason": "operator_override",
            },
            headers=auth(sandbox, idempotency_key=f"f7e-select-{uuid4().hex}"),
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["status"] == "called"
