from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    ReminderOccurrenceResult,
)
from request_engine.modules.communications.adapters.worker.delivery_worker import (
    DeliveryWorkerOutcome,
    DeliveryWorkerState,
)
from request_engine.modules.communications.adapters.worker.scheduled_worker import (
    CommunicationScheduledActionWorker,
)
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.scheduling.worker import ScheduledActionDisposition


class FakeScheduler:
    def __init__(self) -> None:
        self.completed: list[UUID] = []
        self.dead: list[tuple[UUID, str]] = []
        self.retried: list[tuple[UUID, str]] = []

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[ScheduledActionLease, ...]:
        del limit, lease
        return ()

    async def complete(self, lease: ScheduledActionLease) -> bool:
        self.completed.append(lease.id)
        return True

    async def retry(
        self,
        lease: ScheduledActionLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str:
        del next_attempt_at
        self.retried.append((lease.id, error_class))
        return "pending"

    async def dead_letter(self, lease: ScheduledActionLease, *, error_class: str) -> bool:
        self.dead.append((lease.id, error_class))
        return True


class FakeDelivery:
    def __init__(self) -> None:
        self.processed: list[UUID] = []

    async def process(self, lease: ScheduledActionLease) -> DeliveryWorkerOutcome:
        self.processed.append(lease.id)
        return DeliveryWorkerOutcome(
            action_id=lease.id,
            communication_task_id=lease.subject_id,
            delivery_id=uuid4(),
            state=DeliveryWorkerState.COMPLETED,
            detail="delivered",
        )


class FakeReminders:
    def __init__(self) -> None:
        self.materialized: list[UUID] = []

    async def materialize(self, lease: ScheduledActionLease) -> ReminderOccurrenceResult:
        assert lease.subject_id is not None
        self.materialized.append(lease.id)
        occurrence_at = datetime.now(UTC)
        return ReminderOccurrenceResult(
            reminder_plan_id=lease.subject_id,
            occurrence_at=occurrence_at,
            communication_task_id=uuid4(),
            next_occurrence_at=occurrence_at + timedelta(days=1),
            skipped_reason=None,
        )


def make_lease(
    *,
    action_type: str,
    action_version: int = 1,
    subject_kind: str = "CommunicationTask",
) -> ScheduledActionLease:
    now = datetime.now(UTC)
    return ScheduledActionLease(
        id=uuid4(),
        organization_id=uuid4(),
        claim_token=uuid4(),
        owner_module="communications",
        action_type=action_type,
        action_version=action_version,
        subject_kind=subject_kind,
        subject_id=uuid4(),
        payload={},
        attempt_count=1,
        lease_until=now + timedelta(seconds=60),
    )


@pytest.mark.asyncio
async def test_routes_delivery_action_to_delivery_worker() -> None:
    scheduler = FakeScheduler()
    delivery = FakeDelivery()
    reminders = FakeReminders()
    worker = CommunicationScheduledActionWorker(scheduler, delivery, reminders)
    lease = make_lease(action_type="dispatch_task")

    result = await worker.process(lease)

    assert result.disposition is ScheduledActionDisposition.COMPLETED
    assert delivery.processed == [lease.id]
    assert reminders.materialized == []
    assert scheduler.dead == []


@pytest.mark.asyncio
async def test_materializes_reminder_then_fenced_completes_lease() -> None:
    scheduler = FakeScheduler()
    delivery = FakeDelivery()
    reminders = FakeReminders()
    worker = CommunicationScheduledActionWorker(scheduler, delivery, reminders)
    lease = make_lease(
        action_type="materialize_reminder_occurrence",
        subject_kind="ReminderPlan",
    )

    result = await worker.process(lease)

    assert result.disposition is ScheduledActionDisposition.COMPLETED
    assert reminders.materialized == [lease.id]
    assert scheduler.completed == [lease.id]
    assert delivery.processed == []


@pytest.mark.asyncio
async def test_unknown_communications_action_is_dead_lettered_not_retried() -> None:
    scheduler = FakeScheduler()
    worker = CommunicationScheduledActionWorker(
        scheduler,
        FakeDelivery(),
        FakeReminders(),
    )
    lease = make_lease(action_type="unknown_action", action_version=99)

    result = await worker.process(lease)

    assert result.disposition is ScheduledActionDisposition.DEAD
    assert scheduler.dead == [(lease.id, "unsupported_action:unknown_action:v99")]
    assert scheduler.retried == []
