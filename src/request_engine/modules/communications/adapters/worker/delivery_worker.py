from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from request_engine.modules.communications.adapters.db.delivery_store import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
    RECONCILE_ACTION_TYPE,
    RECONCILE_ACTION_VERSION,
    DeliveryWorkKind,
    PreparedDeliveryWork,
    finalize_provider_result,
    prepare_dispatch,
    prepare_reconciliation,
)
from request_engine.modules.communications.adapters.db.poisoned_task import (
    fail_poisoned_communication_task_if_orphaned,
)
from request_engine.modules.communications.application.errors import (
    DeliveryProviderNotConfigured,
    UnsupportedScheduledAction,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.scheduling.store import lock_action_claim
from request_engine.platform.worker.runtime import LeaseLostWorkError


class DeliveryWorkerState(StrEnum):
    COMPLETED = "completed"
    DEFERRED = "deferred"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class DeliveryWorkerOutcome:
    action_id: UUID
    communication_task_id: UUID | None
    delivery_id: UUID | None
    state: DeliveryWorkerState
    detail: str


class CommunicationDeliveryWorker:
    """Execute communication ScheduledActions with no provider I/O under DB locks."""

    def __init__(
        self,
        session_factory: SessionFactory,
        scheduler: PostgresScheduledActionWorker,
        providers: Mapping[str, CommunicationDeliveryProvider],
        *,
        finalization_lease_extension: timedelta = timedelta(seconds=60),
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler
        self._providers = providers
        if finalization_lease_extension <= timedelta(0) or finalization_lease_extension > timedelta(
            minutes=15
        ):
            raise ValueError("finalization_lease_extension must be > 0 and <= 15 minutes")
        self._finalization_lease_extension = finalization_lease_extension

    async def process(self, lease: ScheduledActionLease) -> DeliveryWorkerOutcome:
        try:
            work = await self._prepare(lease)
        except UnsupportedScheduledAction:
            await self._fail_poisoned_task(lease, reason="unsupported_scheduled_action")
            if not await self._scheduler.dead_letter(
                lease,
                error_class="unsupported_scheduled_action",
            ):
                raise LeaseLostWorkError("poison_dead_letter_fence_lost")
            raise
        except ValueError:
            await self._fail_poisoned_task(lease, reason="invalid_scheduled_action")
            if not await self._scheduler.dead_letter(
                lease,
                error_class="invalid_scheduled_action",
            ):
                raise LeaseLostWorkError("poison_dead_letter_fence_lost")
            raise

        if work.kind is DeliveryWorkKind.SKIP:
            if not await self._scheduler.complete(lease):
                raise LeaseLostWorkError("delivery_completion_fence_lost")
            return DeliveryWorkerOutcome(
                action_id=lease.id,
                communication_task_id=work.communication_task_id,
                delivery_id=work.delivery_id,
                state=DeliveryWorkerState.COMPLETED,
                detail=work.skip_reason or "no_work",
            )

        provider_key = (
            work.send_request.provider_key
            if work.send_request is not None
            else work.lookup_request.provider_key
            if work.lookup_request is not None
            else None
        )
        if provider_key is None:
            raise RuntimeError("prepared delivery work has no provider request")
        provider = self._providers.get(provider_key)
        if provider is None:
            await self._require_finalization_lease(lease)
            await self._fail_unconfigured_provider(
                lease,
                work,
                provider_key=provider_key,
            )
            if not await self._scheduler.dead_letter(
                lease,
                error_class="provider_not_configured",
            ):
                raise LeaseLostWorkError("provider_dead_letter_fence_lost")
            raise DeliveryProviderNotConfigured(provider_key) from None

        if work.kind is DeliveryWorkKind.SEND:
            assert work.send_request is not None
            try:
                provider_result = await provider.send(work.send_request)
            except Exception as exc:
                provider_result = ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.AMBIGUOUS,
                    retryable=False,
                    result_data={
                        "error_class": type(exc).__name__,
                        "error_phase": "send",
                    },
                )
        else:
            assert work.lookup_request is not None
            try:
                provider_result = await provider.lookup(work.lookup_request)
            except Exception as exc:
                retry_state = await self._scheduler.retry_after(
                    lease,
                    delay=timedelta(seconds=60),
                    error_class=f"lookup_{type(exc).__name__}",
                )
                if retry_state == "stale":
                    raise LeaseLostWorkError("lookup_retry_fence_lost") from exc
                return DeliveryWorkerOutcome(
                    action_id=lease.id,
                    communication_task_id=work.communication_task_id,
                    delivery_id=work.delivery_id,
                    state=(
                        DeliveryWorkerState.DEAD
                        if retry_state == "dead"
                        else DeliveryWorkerState.DEFERRED
                    ),
                    detail=f"lookup_{retry_state}",
                )

        if work.delivery_id is None:
            raise RuntimeError("provider work is missing delivery identity")
        await self._require_finalization_lease(lease)
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            finalized = await finalize_provider_result(
                session,
                organization_id=lease.organization_id,
                delivery_id=work.delivery_id,
                result=provider_result,
            )

        if not await self._scheduler.complete(lease):
            raise LeaseLostWorkError("delivery_completion_fence_lost")
        return DeliveryWorkerOutcome(
            action_id=lease.id,
            communication_task_id=finalized.communication_task_id,
            delivery_id=finalized.delivery_id,
            state=DeliveryWorkerState.COMPLETED,
            detail=finalized.status.value,
        )

    async def _require_finalization_lease(self, lease: ScheduledActionLease) -> None:
        if not await self._scheduler.renew(
            lease,
            extension=self._finalization_lease_extension,
        ):
            raise LeaseLostWorkError("provider_result_finalization_fence_lost")

    async def _fail_poisoned_task(self, lease: ScheduledActionLease, *, reason: str) -> None:
        if (
            lease.owner_module != "communications"
            or lease.subject_kind != "CommunicationTask"
            or lease.subject_id is None
        ):
            return
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            if not await lock_action_claim(
                session,
                action_id=lease.id,
                claim_token=lease.claim_token,
            ):
                raise LeaseLostWorkError("poison_task_failure_fence_lost")
            await fail_poisoned_communication_task_if_orphaned(
                session,
                organization_id=lease.organization_id,
                communication_task_id=lease.subject_id,
                scheduled_action_id=lease.id,
                reason=reason,
            )

    async def _fail_unconfigured_provider(
        self,
        lease: ScheduledActionLease,
        work: PreparedDeliveryWork,
        *,
        provider_key: str,
    ) -> None:
        if work.delivery_id is None:
            raise RuntimeError("provider work is missing delivery identity")
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            await finalize_provider_result(
                session,
                organization_id=lease.organization_id,
                delivery_id=work.delivery_id,
                result=ProviderDeliveryResult(
                    status=ProviderDeliveryStatus.FAILED,
                    retryable=False,
                    result_data={
                        "error_class": "provider_not_configured",
                        "error_phase": "provider_resolution",
                        "provider_key": provider_key,
                    },
                ),
            )

    async def _prepare(self, lease: ScheduledActionLease) -> PreparedDeliveryWork:
        if (
            lease.owner_module == "communications"
            and lease.action_type == DISPATCH_ACTION_TYPE
            and lease.action_version == DISPATCH_ACTION_VERSION
            and lease.subject_kind == "CommunicationTask"
            and lease.subject_id is not None
        ):
            _validate_payload_identity(
                lease,
                field="communication_task_id",
                expected=lease.subject_id,
            )
            async with tenant_transaction(
                self._session_factory,
                lease.organization_id,
            ) as session:
                if not await lock_action_claim(
                    session,
                    action_id=lease.id,
                    claim_token=lease.claim_token,
                ):
                    raise LeaseLostWorkError("delivery_prepare_fence_lost")
                return await prepare_dispatch(
                    session,
                    organization_id=lease.organization_id,
                    communication_task_id=lease.subject_id,
                )

        if (
            lease.owner_module == "communications"
            and lease.action_type == RECONCILE_ACTION_TYPE
            and lease.action_version == RECONCILE_ACTION_VERSION
            and lease.subject_kind == "CommunicationDelivery"
            and lease.subject_id is not None
        ):
            _validate_payload_identity(
                lease,
                field="delivery_id",
                expected=lease.subject_id,
            )
            async with tenant_transaction(
                self._session_factory,
                lease.organization_id,
            ) as session:
                if not await lock_action_claim(
                    session,
                    action_id=lease.id,
                    claim_token=lease.claim_token,
                ):
                    raise LeaseLostWorkError("reconciliation_prepare_fence_lost")
                return await prepare_reconciliation(
                    session,
                    organization_id=lease.organization_id,
                    delivery_id=lease.subject_id,
                )

        raise UnsupportedScheduledAction(
            lease.owner_module,
            lease.action_type,
            lease.action_version,
        )


def _validate_payload_identity(
    lease: ScheduledActionLease,
    *,
    field: str,
    expected: UUID,
) -> None:
    raw = lease.payload.get(field)
    if not isinstance(raw, str) or UUID(raw) != expected:
        raise ValueError(f"scheduled action payload {field} does not match subject identity")
