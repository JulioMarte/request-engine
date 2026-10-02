"""Fenced prepare -> secret provider I/O -> finalize for staff invitation mail."""

from dataclasses import dataclass
from datetime import timedelta
from typing import cast

from sqlalchemy import text

from request_engine.modules.communications.adapters.db.staff_invitation_delivery import (
    STAFF_INVITATION_DISPATCH,
    STAFF_INVITATION_MAX_ATTEMPTS,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.scheduling.store import lock_action_claim
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    RecoverySecretDelivery,
)
from request_engine.platform.worker.runtime import (
    LeaseLostWorkError,
    PermanentWorkError,
    RetryableWorkError,
)


@dataclass(frozen=True, slots=True)
class _PreparedInvitationDelivery:
    reference: str
    destination: str
    send: bool


class StaffInvitationDeliveryScheduledHandler:
    def __init__(
        self,
        session_factory: SessionFactory,
        scheduler: PostgresScheduledActionWorker,
        delivery: RecoverySecretDelivery | None,
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler
        self._delivery = delivery

    async def handle(self, lease: ScheduledActionLease) -> None:
        _validate_lease(lease)
        work = await self._prepare(lease)
        if work is None:
            return
        outcome = DeliveryOutcome.UNKNOWN
        retryable = False
        error_class: str | None = None
        key = f"staff-invitation-delivery:{lease.subject_id}:v1"
        if self._delivery is None:
            outcome = DeliveryOutcome.FAILED
            error_class = "invitation_delivery_unavailable"
        else:
            try:
                if work.send:
                    outcome = await self._delivery.publish(
                        reference=work.reference,
                        destination_reference=work.destination,
                        idempotency_key=key,
                    )
                else:
                    reconciled = await self._delivery.reconcile(
                        reference=work.reference,
                        idempotency_key=key,
                    )
                    outcome = reconciled or DeliveryOutcome.UNKNOWN
            except RecoveryDeliveryRetryable:
                # Only publish's declared non-transmission failure permits send again.
                retryable = work.send
                error_class = "invitation_delivery_retryable"
            except RecoveryDeliveryPermanent:
                # Lookup failure does not prove the previously sent mail failed.
                outcome = DeliveryOutcome.FAILED if work.send else DeliveryOutcome.UNKNOWN
                error_class = "invitation_delivery_permanent"
            except Exception:
                error_class = "invitation_delivery_ambiguous"
        if retryable and lease.attempt_count >= STAFF_INVITATION_MAX_ATTEMPTS:
            retryable = False
            outcome = DeliveryOutcome.FAILED
            error_class = "invitation_delivery_retry_exhausted"
        if not await self._scheduler.renew(lease, extension=timedelta(seconds=60)):
            raise LeaseLostWorkError("invitation_delivery_finalization_fence_lost")
        finalized = await self._finalize(
            lease,
            outcome=outcome,
            retryable=retryable,
            error_class=error_class,
        )
        if finalized and (retryable or outcome is DeliveryOutcome.UNKNOWN):
            raise RetryableWorkError(error_class or "invitation_delivery_reconcile_required")

    async def _prepare(self, lease: ScheduledActionLease) -> _PreparedInvitationDelivery | None:
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            if not await lock_action_claim(
                session, action_id=lease.id, claim_token=lease.claim_token
            ):
                raise LeaseLostWorkError("invitation_delivery_prepare_fence_lost")
            row = (
                (
                    await session.execute(
                        text("""
                        SELECT status, secret_reference, destination_address,
                               expires_at <= clock_timestamp() AS expired
                        FROM request_engine.staff_invitation_deliveries
                        WHERE organization_id = :org AND id = :id FOR UPDATE
                    """),
                        {"org": lease.organization_id, "id": lease.subject_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] not in ("pending", "attempting", "unknown"):
                return None
            if row["expired"]:
                await session.execute(
                    text("""
                        UPDATE request_engine.staff_invitation_deliveries
                        SET status = 'expired', updated_at = clock_timestamp()
                        WHERE organization_id = :org AND id = :id
                    """),
                    {"org": lease.organization_id, "id": lease.subject_id},
                )
                return None
            send = row["status"] == "pending"
            if send:
                await session.execute(
                    text("""
                        UPDATE request_engine.staff_invitation_deliveries
                        SET status = 'attempting', attempt_no = attempt_no + 1,
                            attempted_at = clock_timestamp(), updated_at = clock_timestamp()
                        WHERE organization_id = :org AND id = :id
                    """),
                    {"org": lease.organization_id, "id": lease.subject_id},
                )
            return _PreparedInvitationDelivery(
                reference=cast(str, row["secret_reference"]),
                destination=cast(str, row["destination_address"]),
                send=send,
            )

    async def _finalize(
        self,
        lease: ScheduledActionLease,
        *,
        outcome: DeliveryOutcome,
        retryable: bool,
        error_class: str | None,
    ) -> bool:
        status = "pending" if retryable else outcome.value
        async with tenant_transaction(self._session_factory, lease.organization_id) as session:
            if not await lock_action_claim(
                session, action_id=lease.id, claim_token=lease.claim_token
            ):
                raise LeaseLostWorkError("invitation_delivery_finalization_fence_lost")
            result = await session.execute(
                text("""
                    UPDATE request_engine.staff_invitation_deliveries
                    SET status = :status, last_error_class = :error,
                        updated_at = clock_timestamp()
                    WHERE organization_id = :org AND id = :id
                      AND status IN ('attempting', 'unknown') RETURNING id
                """),
                {
                    "status": status,
                    "error": error_class,
                    "org": lease.organization_id,
                    "id": lease.subject_id,
                },
            )
            return result.scalar_one_or_none() is not None


def _validate_lease(lease: ScheduledActionLease) -> None:
    if (
        lease.owner_module != "communications"
        or lease.action_type != STAFF_INVITATION_DISPATCH
        or lease.action_version != 1
        or lease.subject_kind != "StaffInvitationDelivery"
        or lease.subject_id is None
        or lease.payload != {"delivery_id": str(lease.subject_id)}
    ):
        raise PermanentWorkError("unsupported_staff_invitation_delivery_action")
