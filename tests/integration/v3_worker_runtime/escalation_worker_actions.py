"""Real scheduled-action drivers for the S3 escalation worker-surface proofs.

These helpers exercise the production execution surface: a real
``ScheduledAction`` row claimed through the platform scheduler and executed by
the real ``CommunicationDeliveryScheduledHandler``.
"""

from datetime import UTC, datetime
from uuid import UUID

from request_engine.modules.communications.adapters.db.dispatch_actions import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reconcile_scheduling import (
    RECONCILE_ACTION_TYPE,
    RECONCILE_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.scheduling.store import schedule_action


async def schedule_dispatch_action(
    session_factory: SessionFactory,
    organization_id: UUID,
    communication_task_id: UUID,
) -> None:
    async with tenant_transaction(session_factory, organization_id) as session:
        await schedule_action(
            session,
            organization_id=organization_id,
            owner_module="communications",
            action_type=DISPATCH_ACTION_TYPE,
            action_version=DISPATCH_ACTION_VERSION,
            subject_kind="CommunicationTask",
            subject_id=communication_task_id,
            dedupe_key=f"communications:dispatch:{communication_task_id}:v1",
            execute_at=datetime.now(UTC),
            payload={"communication_task_id": str(communication_task_id)},
            max_attempts=8,
        )


async def schedule_reconcile_action(
    session_factory: SessionFactory,
    organization_id: UUID,
    delivery_id: UUID,
) -> None:
    async with tenant_transaction(session_factory, organization_id) as session:
        await schedule_action(
            session,
            organization_id=organization_id,
            owner_module="communications",
            action_type=RECONCILE_ACTION_TYPE,
            action_version=RECONCILE_ACTION_VERSION,
            subject_kind="CommunicationDelivery",
            subject_id=delivery_id,
            dedupe_key=f"communications:reconcile:{delivery_id}:worker-proof:v1",
            execute_at=datetime.now(UTC),
            payload={"delivery_id": str(delivery_id)},
            max_attempts=12,
        )


async def claim_and_drive(
    scheduler: PostgresScheduledActionWorker,
    handler: CommunicationDeliveryScheduledHandler,
    subject_id: UUID,
) -> bool:
    """Claim the subject's action through the real scheduler and run the handler."""

    leases = await scheduler.claim(limit=100)
    lease = next(item for item in leases if item.subject_id == subject_id)
    await handler.handle(lease)
    return bool(await scheduler.complete(lease))
