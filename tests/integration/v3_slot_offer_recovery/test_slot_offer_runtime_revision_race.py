# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
    accept_slot_offer,
)
from request_engine.modules.queue.application.commands.decline_slot_offer import (
    DeclineSlotOfferCommand,
    decline_slot_offer,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    offer_next_waitlist_candidate,
)
from request_engine.modules.queue.application.errors import SlotOfferRevisionConflict
from request_engine.platform.db.session import SessionFactory

from .test_slot_offer_recovery import _fixture, _offer_command, _prepare

PgConnection = Connection[Any]


def _waiter_count(admin_conn: PgConnection) -> int:
    row = admin_conn.execute(
        """
        SELECT count(DISTINCT pid)
        FROM pg_locks
        WHERE NOT granted
          AND pid IS NOT NULL
          AND pid <> pg_backend_pid()
        """
    ).fetchone()
    assert row is not None
    return int(row[0])


async def _wait_for_two_new_waiters(admin_conn: PgConnection, baseline: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if _waiter_count(admin_conn) >= baseline + 2:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected both SlotOffer writers to wait on PostgreSQL locking")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_slot_offer_accept_vs_decline_same_revision_uses_real_app_runtime(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, _, _ = await _prepare(fixture, app_session_factory)
    offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(fixture, opportunity_id, key=f"runtime-race-offer-{uuid4().hex}"),
    )
    assert offer is not None

    with admin_conn.transaction():
        locked = admin_conn.execute(
            """
            SELECT id
            FROM request_engine.slot_opportunities
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, opportunity_id),
        ).fetchone()
        assert locked == (opportunity_id,)
        baseline = _waiter_count(admin_conn)
        accept_task = asyncio.create_task(
            accept_slot_offer(
                commands,
                AcceptSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"runtime-accept-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            )
        )
        decline_task = asyncio.create_task(
            decline_slot_offer(
                commands,
                DeclineSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"runtime-decline-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            )
        )
        await _wait_for_two_new_waiters(admin_conn, baseline)
        assert not accept_task.done()
        assert not decline_task.done()

    accept_result, decline_result = await asyncio.gather(
        accept_task,
        decline_task,
        return_exceptions=True,
    )
    outcomes = (accept_result, decline_result)
    successes = [item for item in outcomes if not isinstance(item, BaseException)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], SlotOfferRevisionConflict)

    state = admin_conn.execute(
        """
        SELECT so.status, h.status, o.status, so.revision
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id AND h.id = so.capacity_hold_id
        JOIN request_engine.slot_opportunities o
          ON o.organization_id = so.organization_id AND o.id = so.slot_opportunity_id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone()
    assert state is not None
    assert state[3] == offer.revision + 1
    if state[0] == "accepted":
        assert state[1:3] == ("consumed", "filled")
    else:
        assert state[0:3] == ("declined", "released", "open")
