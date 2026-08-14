from collections.abc import Mapping
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
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.worker.runtime import PermanentWorkError, RetryableWorkError


class CommunicationDeliveryScheduledHandler:
    """Execute provider work while the generic runtime owns lease finalization."""

    def __init__(
        self,
        session_factory: SessionFactory,
        providers: Mapping[str, CommunicationDeliveryProvider],
    ) -> None:
        self._session_factory = session_factory
        self._providers = providers

    async def handle(self, lease: ScheduledActionLease) -> None:
        work = await self._prepare(lease)
        if work.kind is DeliveryWorkKind.SKIP:
            return

        provider_key = (
            work.send_request.provider_key
            if work.send_request is not None
            else work.lookup_request.provider_key
            if work.lookup_request is not None
            else None
        )
        if provider_key is None:
            raise PermanentWorkError("prepared_delivery_missing_provider")
        provider = self._providers.get(provider_key)
        if provider is None:
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
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            await finalize_provider_result(
                session,
                organization_id=lease.organization_id,
                delivery_id=work.delivery_id,
                result=provider_result,
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
    if not isinstance(raw, str) or UUID(raw) != expected:
        raise PermanentWorkError(
            "scheduled_action_payload_mismatch",
            f"ScheduledAction payload {field} does not match subject identity",
        )
