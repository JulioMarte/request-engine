from uuid import uuid4

import pytest

from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.application.commands.triage import (
    RecallHoldCommand,
    ReleaseRecallHoldCommand,
    SkipCommand,
)
from request_engine.modules.queue.contracts.triage import RecallHoldKind, SkipReason
from request_engine.platform.db.session import SessionFactory

from .triage_scenario import PgConnection, create_world


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_staff_read_explains_active_recall_hold_and_release(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)
    reader = PostgresLiveQueueReader(app_session_factory)

    held = await triage.recall_hold(
        RecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            condition_kind=RecallHoldKind.UNTIL_CUSTOMER_INITIATES,
            expected_revision=1,
            idempotency_key=f"hold-{uuid4().hex}",
            reason="patient stepped out",
        )
    )
    assert held.hold is not None

    waiting = await reader.staff_queue(organization_id, queue_id)
    assert len(waiting) == 1
    projected = waiting[0]
    assert projected.queue_entry_id == entries[0]
    assert projected.recall_eligible is False
    assert projected.recall_hold_id == held.hold.id
    assert projected.recall_hold_kind == RecallHoldKind.UNTIL_CUSTOMER_INITIATES
    assert projected.recall_hold_reason == "patient stepped out"
    assert projected.active_skip_reason is None

    await triage.release_recall_hold(
        ReleaseRecallHoldCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            hold_id=held.hold.id,
            expected_revision=2,
            idempotency_key=f"release-{uuid4().hex}",
        )
    )

    released = await reader.staff_queue(organization_id, queue_id)
    assert len(released) == 1
    projected = released[0]
    assert projected.recall_eligible is True
    assert projected.recall_hold_id is None
    assert projected.recall_hold_kind is None
    assert projected.recall_hold_reason is None


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_staff_read_explains_one_shot_skip_without_inventing_readiness_state(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, queue_id, entries = create_world(admin_conn, 1)
    triage = PostgresQueueTriageCommands(app_session_factory)
    reader = PostgresLiveQueueReader(app_session_factory)

    await triage.skip(
        SkipCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_entry_id=entries[0],
            reason=SkipReason.TEMPORARILY_UNAVAILABLE,
            expected_revision=1,
            idempotency_key=f"skip-{uuid4().hex}",
        )
    )

    waiting = await reader.staff_queue(organization_id, queue_id)
    assert len(waiting) == 1
    projected = waiting[0]
    assert projected.recall_eligible is False
    assert projected.active_skip_reason == SkipReason.TEMPORARILY_UNAVAILABLE
    assert projected.recall_hold_id is None
