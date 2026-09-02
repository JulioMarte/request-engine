import asyncio
from uuid import uuid4

import pytest
from f7e_selection_fixture import PgConnection, create_f7e_selection_fixture
from f7e_selection_race_barrier import AsyncTwoPartyBarrier, gated_lock

from request_engine.modules.queue.adapters.db import operator_select as select_module
from request_engine.modules.queue.adapters.db import service_queue_commands as queue_module
from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.application.commands.call_next import CallNextCommand
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.same_day_selection_errors import (
    QueueEntryNotSelectable,
)
from request_engine.modules.queue.contracts.same_day_selection import OperatorSelectReason
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_call_next_vs_operator_select_never_double_calls_target(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = create_f7e_selection_fixture(admin_conn)
    first, second, _third = world.entry_ids
    barrier = AsyncTwoPartyBarrier()
    monkeypatch.setattr(
        queue_module,
        "lock_active_queue",
        gated_lock(barrier, queue_module.lock_active_queue),
    )
    monkeypatch.setattr(
        select_module,
        "lock_active_queue",
        gated_lock(barrier, select_module.lock_active_queue),
    )
    queue = PostgresServiceQueueCommands(command_session_factory)
    f7e = PostgresSameDaySelectionCommands(command_session_factory)

    results = await asyncio.gather(
        queue.call_next(
            CallNextCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                idempotency_key=f"call-select-{uuid4().hex}",
            )
        ),
        f7e.operator_select(
            OperatorSelectCommand(
                organization_id=world.organization_id,
                principal_id=world.principal_id,
                queue_id=world.queue_id,
                queue_entry_id=first,
                expected_revision=1,
                reason=OperatorSelectReason.OPERATOR_OVERRIDE,
                idempotency_key=f"operator-select-{uuid4().hex}",
            )
        ),
        return_exceptions=True,
    )

    called_entries = [item.id for item in results if isinstance(item, QueueEntry)]
    rejected = [item for item in results if isinstance(item, QueueEntryNotSelectable)]
    assert (called_entries == [first] and len(rejected) == 1) or set(called_entries) == {
        first,
        second,
    }, repr(results)
    rows = admin_conn.execute(
        "SELECT id,status,revision FROM request_engine.queue_entries "
        "WHERE id IN (%s,%s) ORDER BY admitted_at,id",
        (first, second),
    ).fetchall()
    assert rows[0][1:] == ("called", 2)
    assert rows[1][1:] in (("waiting", 1), ("called", 2))
    facts = admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_selection_facts "
        "WHERE organization_id=%s AND selection_kind='operator_select'",
        (world.organization_id,),
    ).fetchone()
    assert facts is not None and facts[0] in (0, 1)
