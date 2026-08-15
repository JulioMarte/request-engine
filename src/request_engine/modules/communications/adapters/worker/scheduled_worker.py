from datetime import UTC, datetime
from typing import Protocol

from request_engine.modules.communications.adapters.db.delivery_store import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
    RECONCILE_ACTION_TYPE,
    RECONCILE_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_ACTION_TYPE,
    REMINDER_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    ReminderOccurrenceResult,
)
from request_engine.modules.communications.adapters.worker.delivery_worker import (
    DeliveryWorkerOutcome,
    DeliveryWorkerState,
)
from request_engine.modules.communications.application.errors import (
    DeliveryProviderNotConfigured,
    UnsupportedScheduledAction,
)
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.scheduling.worker import (
    ScheduledActionDisposition,
    ScheduledActionLeaseStore,
    ScheduledActionProcessResult,
    retry_delay,
)


class DeliveryActionProcessor(Protocol):
    async def process(self, lease: ScheduledActionLease) -> DeliveryWorkerOutcome: ...


class ReminderOccurrenceProcessor(Protocol):
    async def materialize(self, lease: ScheduledActionLease) -> ReminderOccurrenceResult: ...


class CommunicationScheduledActionWorker:
    """Own communications ScheduledAction routing and lease finalization policy."""

    def __init__(
        self,
        scheduler: ScheduledActionLeaseStore,
        delivery: DeliveryActionProcessor,
        reminders: ReminderOccurrenceProcessor,
    ) -> None:
        self._scheduler = scheduler
        self._delivery = delivery
        self._reminders = reminders

    async def process(self, lease: ScheduledActionLease) -> ScheduledActionProcessResult:
        if lease.owner_module != "communications":
            return await self._dead_letter(lease, "wrong_owner_module")

        if _is_delivery_action(lease):
            try:
                outcome = await self._delivery.process(lease)
            except DeliveryProviderNotConfigured:
                # DeliveryWorker already fenced this lease into dead-letter state.
                return ScheduledActionProcessResult(
                    ScheduledActionDisposition.DEAD,
                    "provider_not_configured",
                )
            except (UnsupportedScheduledAction, ValueError) as exc:
                return await self._dead_letter(lease, type(exc).__name__)
            except Exception as exc:
                return await self._retry(lease, type(exc).__name__)

            disposition = {
                DeliveryWorkerState.COMPLETED: ScheduledActionDisposition.COMPLETED,
                DeliveryWorkerState.DEFERRED: ScheduledActionDisposition.DEFERRED,
                DeliveryWorkerState.DEAD: ScheduledActionDisposition.DEAD,
            }[outcome.state]
            return ScheduledActionProcessResult(disposition, outcome.detail)

        if _is_reminder_action(lease):
            try:
                result = await self._reminders.materialize(lease)
            except (UnsupportedScheduledAction, ValueError) as exc:
                return await self._dead_letter(lease, type(exc).__name__)
            except Exception as exc:
                return await self._retry(lease, type(exc).__name__)

            completed = await self._scheduler.complete(lease)
            return ScheduledActionProcessResult(
                (
                    ScheduledActionDisposition.COMPLETED
                    if completed
                    else ScheduledActionDisposition.STALE
                ),
                result.skipped_reason or "reminder_materialized",
            )

        return await self._dead_letter(
            lease,
            f"unsupported_action:{lease.action_type}:v{lease.action_version}",
        )

    async def _retry(
        self,
        lease: ScheduledActionLease,
        error_class: str,
    ) -> ScheduledActionProcessResult:
        retry_state = await self._scheduler.retry(
            lease,
            next_attempt_at=datetime.now(UTC) + retry_delay(lease.attempt_count),
            error_class=error_class,
        )
        disposition = {
            "pending": ScheduledActionDisposition.DEFERRED,
            "dead": ScheduledActionDisposition.DEAD,
            "stale": ScheduledActionDisposition.STALE,
        }.get(retry_state, ScheduledActionDisposition.STALE)
        return ScheduledActionProcessResult(disposition, f"retry:{retry_state}:{error_class}")

    async def _dead_letter(
        self,
        lease: ScheduledActionLease,
        error_class: str,
    ) -> ScheduledActionProcessResult:
        finalized = await self._scheduler.dead_letter(lease, error_class=error_class)
        return ScheduledActionProcessResult(
            ScheduledActionDisposition.DEAD if finalized else ScheduledActionDisposition.STALE,
            error_class,
        )


def _is_delivery_action(lease: ScheduledActionLease) -> bool:
    return (
        lease.action_type == DISPATCH_ACTION_TYPE
        and lease.action_version == DISPATCH_ACTION_VERSION
    ) or (
        lease.action_type == RECONCILE_ACTION_TYPE
        and lease.action_version == RECONCILE_ACTION_VERSION
    )


def _is_reminder_action(lease: ScheduledActionLease) -> bool:
    return (
        lease.action_type == REMINDER_ACTION_TYPE
        and lease.action_version == REMINDER_ACTION_VERSION
    )
