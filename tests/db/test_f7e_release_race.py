import asyncio
from uuid import uuid4

import pytest

from f7e_selection_assertions import call_next_command
from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from f7e_selection_race_barrier import AsyncTwoPartyBarrier, gated_lock
from request_engine.modules.queue.adapters.db import release_recall_hold as release_module
from request_engine.modules.queue.adapters.db import service_queue_commands as queue_module
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.contracts.same_day_selection import RecallHoldKind, RecallHoldReason
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_release_vs_call_next_has_only_serialized_selection_outcomes(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    f7e = PostgresSameDaySelectionCommands(command_session_factory)
    hold = await f7e.recall_hold(
        RecallHoldCommand(
            world.organization_id,
            world.principal_id,
            world.queue_id,
            first,
            1,
            RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            None,
            RecallHoldReason.STEPPED_AWAY,
            f"release-race-hold-{uuid4().hex}",
        )
    )
    barrier = AsyncTwoPartyBarrier()
    monkeypatch.setattr(
        queue_module,
        "_lock_active_queue",
        gated_lock(barrier, queue_module._lock_active_queue),
    )
    monkeypatch.setattr(
        release_module,
        "lock_active_queue",
        gated_lock(barrier, release_module.lock_active_queue),
    )
    queue = PostgresServiceQueueCommands(command_session_factory)

    called, released = await asyncio.gather(
        queue.call_next(call_next_command(world, "release-race")),
        f7e.release_recall_hold(
            ReleaseRecallHoldCommand(
                world.organization_id,
                world.principal_id,
                world.queue_id,
                first,
                hold.id,
                hold.queue_entry_revision,
                f"release-race-release-{uuid4().hex}",
            )
        ),
    )

    assert called is not None and released is not None
    assert called.id in {first, second}
    statuses = dict(
        admin_conn.execute(
            "SELECT id,status FROM request_engine.queue_entries WHERE id IN (%s,%s)",
            (first, second),
        ).fetchall()
    )
    assert statuses[called.id] == "called"
    assert sum(status == "called" for status in statuses.values()) == 1
    active = admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_recall_holds "
        "WHERE queue_entry_id=%s AND released_at IS NULL",
        (first,),
    ).fetchone()
    assert active == (0,)
    if called.id == first:
        assert statuses[second] == "waiting"
    else:
        assert statuses[first] == "waiting"
