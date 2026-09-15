"""Technical secret-delivery boundary for governed identity recovery (D2).

The raw recovery proof never enters PostgreSQL, the audit boundary, the
ordinary outbox or an administrative response. A dedicated adapter stages it
with a TTL under an opaque reference; the platform control plane stores only
the reference, its fingerprint and the delivery ticket. Publishing happens
outside authoritative locks and is finalized under a lease/fence.

This module owns the contract, not a provider. A deployment must select and
configure a real adapter (D6); without one the control plane fails closed.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    UNKNOWN = "unknown"
    FAILED = "failed"


class RecoveryDeliveryError(RuntimeError):
    """Base class for technical recovery-secret delivery failures."""


class RecoveryDeliveryUnavailable(RecoveryDeliveryError):
    """No delivery adapter is configured; issuance must fail closed."""


class RecoveryDeliveryRetryable(RecoveryDeliveryError):
    """The delivery attempt failed in a way that may succeed later."""


class RecoveryDeliveryPermanent(RecoveryDeliveryError):
    """The delivery attempt failed permanently; do not retry blindly."""


@dataclass(frozen=True, slots=True)
class StagedRecoverySecret:
    """Opaque metadata for a staged proof. Never carries the raw secret."""

    reference: str
    digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.reference.strip():
            raise ValueError("staged secret reference is required")
        if len(self.digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.digest
        ):
            raise ValueError("staged secret digest must be 64 lowercase hex characters")


class RecoverySecretDelivery(Protocol):
    """Create-if-absent staging plus fenced, idempotent publication.

    ``stage`` is keyed by ``(case_id, generation)`` and MUST return the secret
    that was actually retained: on replay or a concurrent candidate it returns
    the existing reference/digest and the caller discards its own candidate.
    ``publish`` MUST NOT be retried blindly on an ambiguous outcome; callers
    reconcile first with the same idempotency key.
    """

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret: ...

    async def discard(self, *, case_id: UUID, generation: int) -> None: ...

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome: ...

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None: ...
