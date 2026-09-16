"""Internal store/channel split behind the RecoverySecretDelivery port."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.secrets.delivery import DeliveryOutcome, StagedRecoverySecret


class RecoverySecretStore(Protocol):
    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret: ...

    async def discard(self, *, case_id: UUID, generation: int) -> None: ...

    async def read(self, *, reference: str) -> str: ...


class RecoveryDeliveryChannel(Protocol):
    async def send(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome: ...

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None: ...
