"""Compose a staging store and a delivery channel into the delivery port.

The port separates secret retention from secret transmission so a deployment
can pair a Vault-backed store with an SMTP or WhatsApp channel. Publication
reads the retained secret back from the store immediately before transmission,
so the raw proof never travels with the durable delivery ticket.
"""

from datetime import datetime
from uuid import UUID

from request_engine.platform.secrets.delivery import DeliveryOutcome, StagedRecoverySecret
from request_engine.platform.secrets.delivery_parts import (
    RecoveryDeliveryChannel,
    RecoverySecretStore,
)


class ComposedRecoverySecretDelivery:
    """Structural implementation of ``RecoverySecretDelivery`` over two parts."""

    def __init__(
        self,
        *,
        store: RecoverySecretStore,
        channel: RecoveryDeliveryChannel,
    ) -> None:
        self._store = store
        self._channel = channel

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        return await self._store.stage(
            case_id=case_id,
            generation=generation,
            secret=secret,
            expires_at=expires_at,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        await self._store.discard(case_id=case_id, generation=generation)

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        secret = await self._store.read(reference=reference)
        return await self._channel.send(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None:
        return await self._channel.reconcile(idempotency_key=idempotency_key)
