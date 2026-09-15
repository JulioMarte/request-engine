"""Fenced delivery-ticket worker for governed identity recovery.

The processor publishes the staged proof through the technical delivery port
and finalizes the durable ticket with its claim token. Delivery I/O never runs
inside the authoritative issuance transaction; a lost fence prevents the late
result from overwriting the current owner of the ticket.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
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

_COMPLETION_OUTCOMES = frozenset({"delivered", "unknown", "failed"})


@dataclass(frozen=True, slots=True)
class RecoveryDeliveryLease:
    id: UUID
    case_id: UUID
    generation: int
    secret_reference: str
    secret_digest: str
    destination_reference: str
    expires_at: datetime
    attempt_count: int
    claim_token: UUID


class PostgresRecoveryDeliveryLeaseStore:
    """Fenced lease store over the recovery delivery-ticket worker surface."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[RecoveryDeliveryLease, ...]:
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        lease_seconds = lease.total_seconds()
        if lease_seconds <= 0 or lease_seconds > 900:
            raise ValueError("lease must be > 0 and <= 15 minutes")
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_platform.claim_identity_recovery_delivery_tickets(
                                CAST(:limit AS integer),
                                CAST(:lease_seconds AS integer)
                            )
                            """
                        ),
                        {"limit": limit, "lease_seconds": math.ceil(lease_seconds)},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            RecoveryDeliveryLease(
                id=cast(UUID, row["ticket_id"]),
                case_id=cast(UUID, row["case_id"]),
                generation=cast(int, row["generation"]),
                secret_reference=cast(str, row["secret_reference"]),
                secret_digest=cast(str, row["secret_digest"]),
                destination_reference=cast(str, row["destination_reference"]),
                expires_at=cast(datetime, row["expires_at"]),
                attempt_count=cast(int, row["attempt_count"]),
                claim_token=cast(UUID, row["claim_token"]),
            )
            for row in rows
        )

    async def complete(
        self,
        lease: RecoveryDeliveryLease,
        *,
        outcome: str | None = None,
        error_class: str | None = None,
    ) -> bool:
        if outcome is None:
            # The processor finalizes the ticket under its claim token before
            # returning; the runtime's confirmation is not a second fenced
            # write and must not try to clear an already-terminal ticket.
            return True
        if outcome not in _COMPLETION_OUTCOMES:
            raise ValueError("outcome must be one of 'delivered', 'unknown', 'failed'")
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_platform.complete_identity_recovery_delivery_ticket(
                                CAST(:id AS uuid),
                                CAST(:token AS uuid),
                                CAST(:outcome AS text),
                                CAST(:error AS text)
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "outcome": outcome,
                            "error": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def retry_after(
        self,
        lease: RecoveryDeliveryLease,
        *,
        delay: timedelta,
        error_class: str,
    ) -> str:
        seconds = delay.total_seconds()
        if seconds < 0 or seconds > 86400:
            raise ValueError("retry delay must be between 0 and 24 hours")
        async with self._session_factory() as session, session.begin():
            return cast(
                str,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_platform.retry_identity_recovery_delivery_ticket(
                                CAST(:id AS uuid),
                                CAST(:token AS uuid),
                                CAST(:delay_seconds AS integer),
                                CAST(:error_class AS text)
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "delay_seconds": math.ceil(seconds),
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def dead_letter(self, lease: RecoveryDeliveryLease, *, error_class: str) -> bool:
        return await self.complete(lease, outcome="failed", error_class=error_class)

    async def renew(self, lease: RecoveryDeliveryLease, *, extension: timedelta) -> bool:
        seconds = extension.total_seconds()
        if seconds <= 0 or seconds > 900:
            raise ValueError("lease extension must be > 0 and <= 15 minutes")
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_platform.renew_identity_recovery_delivery_ticket_lease(
                                CAST(:id AS uuid),
                                CAST(:token AS uuid),
                                CAST(:extension_seconds AS integer)
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "extension_seconds": math.ceil(seconds),
                        },
                    )
                ).scalar_one(),
            )


class RecoveryDeliveryProcessor:
    """Publish a staged recovery proof and finalize its delivery ticket."""

    def __init__(
        self,
        store: PostgresRecoveryDeliveryLeaseStore,
        delivery: RecoverySecretDelivery,
    ) -> None:
        self._store = store
        self._delivery = delivery

    async def process(self, lease: RecoveryDeliveryLease) -> None:
        idempotency_key = f"{lease.case_id}:{lease.generation}"
        outcome = await self._deliver(lease, idempotency_key=idempotency_key)
        await self._finalize(lease, outcome)

    async def _deliver(
        self,
        lease: RecoveryDeliveryLease,
        *,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        try:
            if lease.attempt_count > 1:
                reconciled = await self._delivery.reconcile(
                    reference=lease.secret_reference,
                    idempotency_key=idempotency_key,
                )
                if reconciled is not None:
                    return reconciled
            return await self._delivery.publish(
                reference=lease.secret_reference,
                destination_reference=lease.destination_reference,
                idempotency_key=idempotency_key,
            )
        except RecoveryDeliveryRetryable as exc:
            raise RetryableWorkError(type(exc).__name__) from exc
        except RecoveryDeliveryPermanent as exc:
            raise PermanentWorkError(type(exc).__name__) from exc

    async def _finalize(self, lease: RecoveryDeliveryLease, outcome: DeliveryOutcome) -> None:
        completion = {
            DeliveryOutcome.DELIVERED: ("delivered", None),
            DeliveryOutcome.UNKNOWN: ("unknown", "ambiguous_delivery_outcome"),
            DeliveryOutcome.FAILED: ("failed", "provider_rejected"),
        }[outcome]
        completed = await self._store.complete(
            lease,
            outcome=completion[0],
            error_class=completion[1],
        )
        if not completed:
            raise LeaseLostWorkError("recovery_delivery_completion_fence_lost")
