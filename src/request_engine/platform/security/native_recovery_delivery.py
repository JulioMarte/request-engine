"""Fenced worker for queued Native HUMAN verified-address recovery delivery."""

import math
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
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
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.worker.runtime import (
    LeaseLostWorkError,
    PermanentWorkError,
    RetryableWorkError,
)

_COMPLETION_OUTCOMES = frozenset({"delivered", "unknown", "failed"})
_DEFAULT_PROOF_TTL = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class NativeRecoveryDeliveryLease:
    id: UUID
    native_identity_id: UUID
    recovery_address_id: UUID
    generation: int
    recovery_intent_id: UUID | None
    secret_reference: str | None
    secret_digest: str | None
    destination_reference: str
    proof_expires_at: datetime | None
    attempt_count: int
    claim_token: UUID


class PostgresNativeRecoveryDeliveryLeaseStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[NativeRecoveryDeliveryLease, ...]:
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
                              FROM request_auth.claim_native_recovery_delivery_requests(
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
            NativeRecoveryDeliveryLease(
                id=cast(UUID, row["request_id"]),
                native_identity_id=cast(UUID, row["native_identity_id"]),
                recovery_address_id=cast(UUID, row["recovery_address_id"]),
                generation=cast(int, row["generation"]),
                recovery_intent_id=cast(UUID | None, row["recovery_intent_id"]),
                secret_reference=cast(str | None, row["secret_reference"]),
                secret_digest=cast(str | None, row["secret_digest"]),
                destination_reference=cast(str, row["destination_reference"]),
                proof_expires_at=cast(datetime | None, row["proof_expires_at"]),
                attempt_count=cast(int, row["attempt_count"]),
                claim_token=cast(UUID, row["claim_token"]),
            )
            for row in rows
        )

    async def activate(
        self,
        lease: NativeRecoveryDeliveryLease,
        *,
        recovery_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        proof_expires_at: datetime,
        secret_reference: str,
        secret_digest: str,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_auth.activate_native_recovery_delivery_request(
                                CAST(:request_id AS uuid),
                                CAST(:claim_token AS uuid),
                                CAST(:generation AS integer),
                                CAST(:recovery_id AS uuid),
                                CAST(:token_digest AS bytea),
                                CAST(:token_fingerprint AS text),
                                CAST(:proof_expires_at AS timestamptz),
                                CAST(:secret_reference AS text),
                                CAST(:secret_digest AS text)
                            )
                            """
                        ),
                        {
                            "request_id": lease.id,
                            "claim_token": lease.claim_token,
                            "generation": lease.generation,
                            "recovery_id": recovery_id,
                            "token_digest": token_digest,
                            "token_fingerprint": token_fingerprint,
                            "proof_expires_at": proof_expires_at,
                            "secret_reference": secret_reference,
                            "secret_digest": secret_digest,
                        },
                    )
                ).scalar_one(),
            )

    async def complete(
        self,
        lease: NativeRecoveryDeliveryLease,
        *,
        outcome: str | None = None,
        error_class: str | None = None,
    ) -> bool:
        if outcome is None:
            return True
        if outcome not in _COMPLETION_OUTCOMES:
            raise ValueError("outcome must be delivered, unknown or failed")
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_auth.complete_native_recovery_delivery_request(
                                CAST(:request_id AS uuid),
                                CAST(:claim_token AS uuid),
                                CAST(:outcome AS text),
                                CAST(:error_class AS text)
                            )
                            """
                        ),
                        {
                            "request_id": lease.id,
                            "claim_token": lease.claim_token,
                            "outcome": outcome,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def retry_after(
        self,
        lease: NativeRecoveryDeliveryLease,
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
                            SELECT request_auth.retry_native_recovery_delivery_request(
                                CAST(:request_id AS uuid),
                                CAST(:claim_token AS uuid),
                                CAST(:delay_seconds AS integer),
                                CAST(:error_class AS text)
                            )
                            """
                        ),
                        {
                            "request_id": lease.id,
                            "claim_token": lease.claim_token,
                            "delay_seconds": math.ceil(seconds),
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def dead_letter(
        self,
        lease: NativeRecoveryDeliveryLease,
        *,
        error_class: str,
    ) -> bool:
        return await self.complete(
            lease,
            outcome="failed",
            error_class=error_class,
        )

    async def renew(
        self,
        lease: NativeRecoveryDeliveryLease,
        *,
        extension: timedelta,
    ) -> bool:
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
                            SELECT request_auth.renew_native_recovery_delivery_request_lease(
                                CAST(:request_id AS uuid),
                                CAST(:claim_token AS uuid),
                                CAST(:extension_seconds AS integer)
                            )
                            """
                        ),
                        {
                            "request_id": lease.id,
                            "claim_token": lease.claim_token,
                            "extension_seconds": math.ceil(seconds),
                        },
                    )
                ).scalar_one(),
            )


class NativeRecoveryDeliveryProcessor:
    def __init__(
        self,
        store: PostgresNativeRecoveryDeliveryLeaseStore,
        delivery: RecoverySecretDelivery,
        *,
        proof_ttl: timedelta = _DEFAULT_PROOF_TTL,
    ) -> None:
        if proof_ttl <= timedelta(0) or proof_ttl > timedelta(minutes=30):
            raise ValueError("proof_ttl must be > 0 and <= 30 minutes")
        self._store = store
        self._delivery = delivery
        self._proof_ttl = proof_ttl

    async def process(self, lease: NativeRecoveryDeliveryLease) -> None:
        active_lease = lease
        just_staged = False
        if lease.secret_reference is None:
            active_lease = await self._stage_new_proof(lease)
            just_staged = True

        reference = active_lease.secret_reference
        if reference is None:
            raise PermanentWorkError("native_recovery_secret_reference_missing")

        idempotency_key = f"native-recovery:{active_lease.id}:{active_lease.generation}"
        outcome = await self._deliver(
            active_lease,
            reference=reference,
            idempotency_key=idempotency_key,
            reconcile_first=active_lease.attempt_count > 1 and not just_staged,
        )
        await self._finalize(active_lease, outcome)

    async def _stage_new_proof(
        self,
        lease: NativeRecoveryDeliveryLease,
    ) -> NativeRecoveryDeliveryLease:
        token = issue_opaque_token()
        expires_at = datetime.now(UTC) + self._proof_ttl
        try:
            staged = await self._delivery.stage(
                case_id=lease.id,
                generation=lease.generation,
                secret=token.raw_token,
                expires_at=expires_at,
            )
        except RecoveryDeliveryRetryable as exc:
            raise RetryableWorkError(type(exc).__name__) from exc
        except RecoveryDeliveryPermanent as exc:
            raise PermanentWorkError(type(exc).__name__) from exc

        if not staged.created:
            raise RetryableWorkError("native_recovery_stage_collision")

        activated = await self._store.activate(
            lease,
            recovery_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            proof_expires_at=expires_at,
            secret_reference=staged.reference,
            secret_digest=staged.digest,
        )
        if not activated:
            with suppress(RecoveryDeliveryPermanent, RecoveryDeliveryRetryable):
                await self._delivery.discard(
                    case_id=lease.id,
                    generation=lease.generation,
                )
            raise LeaseLostWorkError("native_recovery_activation_fence_lost")

        return replace(
            lease,
            recovery_intent_id=token.token_id,
            secret_reference=staged.reference,
            secret_digest=staged.digest,
            proof_expires_at=expires_at,
        )

    async def _deliver(
        self,
        lease: NativeRecoveryDeliveryLease,
        *,
        reference: str,
        idempotency_key: str,
        reconcile_first: bool,
    ) -> DeliveryOutcome:
        try:
            if reconcile_first:
                reconciled = await self._delivery.reconcile(
                    reference=reference,
                    idempotency_key=idempotency_key,
                )
                if reconciled is not None:
                    return reconciled
            return await self._delivery.publish(
                reference=reference,
                destination_reference=lease.destination_reference,
                idempotency_key=idempotency_key,
            )
        except RecoveryDeliveryRetryable as exc:
            raise RetryableWorkError(type(exc).__name__) from exc
        except RecoveryDeliveryPermanent as exc:
            raise PermanentWorkError(type(exc).__name__) from exc

    async def _finalize(
        self,
        lease: NativeRecoveryDeliveryLease,
        outcome: DeliveryOutcome,
    ) -> None:
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
            raise LeaseLostWorkError("native_recovery_delivery_completion_fence_lost")
