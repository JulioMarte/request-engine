from collections.abc import Mapping
from datetime import timedelta
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
from request_engine.modules.communications.application.errors import DeliveryConfigurationError
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
from request_engine.platform.worker.runtime import (
    LeaseLostWorkError,
    PermanentWorkError,
    RetryableWorkError,
)


class CommunicationDeliveryScheduledHandler:
    """Execute provider work while the generic runtime owns lease finalization.

    Provider I/O is intentionally outside tenant transactions. Before writing
    its result, the handler renews the same claim token and then validates that
    claim again inside the authoritative tenant transaction. A stale worker can
    therefore make an idempotent provider request but cannot persist its result
    after another worker owns the ScheduledAction.
    """

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
        if not timedelta(0) < finalization_lease_extension <= timedelta(minutes=15):
            raise ValueError("finalization_lease_extension must be > 0 and <= 15 minutes")
        self._finalization_lease_extension = finalization_lease_extension

    async def handle(self, lease: ScheduledActionLease) -> None:
        try:
            work = await self._prepare(lease)
        except DeliveryConfigurationError as exc:
            await self._fail_poisoned_task(lease, reason="delivery_configuration_invalid")
            raise PermanentWorkError("delivery_configuration_invalid", exc.reason) from exc
        except PermanentWorkError as exc:
            await self._fail_poisoned_task(lease, reason=exc.error_class)
            raise
        if work.kind is DeliveryWorkKind.SKIP:
            return

        request = work.send_request if work.send_request is not None else work.lookup_request
        provider_key = request.provider_key if request is not None else None
        if provider_key is None:
            raise PermanentWorkError("prepared_delivery_missing_provider")
        provider = self._providers.get(provider_key)
        if provider is None:
            if work.delivery_id is None:
                raise PermanentWorkError("prepared_delivery_missing_identity")
            await self._require_finalization_lease(lease)
            await self._finalize_owned_provider_result(
                lease,
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
            raise PermanentWorkError("provider_not_configured", provider_key)

        if work.kind is DeliveryWorkKind.SEND:
            assert work.send_request is not None
            try:
                provider_result = await provider.send(work.send_request)
            except Exception as exc:
                # A send-side exception is ambiguous: do not blindly send again.
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
                raise RetryableWorkError(f"lookup_{type(exc).__name__}") from exc

        if work.delivery_id is None:
            raise PermanentWorkError("prepared_delivery_missing_identity")

        await self._require_finalization_lease(lease)
        await self._finalize_owned_provider_result(
            lease,
            delivery_id=work.delivery_id,
            result=provider_result,
        )

    async def _require_finalization_lease(self, lease: ScheduledActionLease) -> None:
        if not await self._scheduler.renew(
            lease,
            extension=self._finalization_lease_extension,
        ):
            raise LeaseLostWorkError("provider_result_finalization_fence_lost")

    async def _finalize_owned_provider_result(
        self,
        lease: ScheduledActionLease,
        *,
        delivery_id: UUID,
        result: ProviderDeliveryResult,
    ) -> None:
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            if not await lock_action_claim(
                session,
                action_id=lease.id,
                claim_token=lease.claim_token,
            ):
                raise LeaseLostWorkError("provider_result_finalization_fence_lost")
            await finalize_provider_result(
                session,
                organization_id=lease.organization_id,
                delivery_id=delivery_id,
                result=result,
            )

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
                    configured_provider_keys=tuple(self._providers),
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

        raise PermanentWorkError(
            "unsupported_communications_scheduled_action",
            f"unsupported communications ScheduledAction {lease.action_type!r}",
        )


def _validate_payload_identity(
    lease: ScheduledActionLease,
    *,
    field: str,
    expected: UUID,
) -> None:
    raw = lease.payload.get(field)
    try:
        payload_id = UUID(raw) if isinstance(raw, str) else None
    except ValueError as exc:
        raise PermanentWorkError(
            "scheduled_action_payload_mismatch",
            f"ScheduledAction payload {field} is not a UUID",
        ) from exc
    if payload_id != expected:
        raise PermanentWorkError(
            "scheduled_action_payload_mismatch",
            f"ScheduledAction payload {field} does not match subject identity",
        )
