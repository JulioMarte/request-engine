from datetime import UTC, datetime
from uuid import UUID

import pytest

from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoverySecretDelivery,
    StagedRecoverySecret,
)

pytestmark = [pytest.mark.unit]

_CASE_ID = UUID("11111111-1111-1111-1111-111111111111")


class _FakeStore:
    def __init__(self, *, secret: str = "stored-raw-secret") -> None:
        self.secret = secret
        self.staged: list[tuple[UUID, int, str, datetime]] = []
        self.discarded: list[tuple[UUID, int]] = []
        self.reads: list[str] = []

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        self.staged.append((case_id, generation, secret, expires_at))
        return StagedRecoverySecret(
            reference=f"ref://{case_id}/{generation}",
            digest="a" * 64,
            expires_at=expires_at,
            created=True,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.discarded.append((case_id, generation))

    async def read(self, *, reference: str) -> str:
        self.reads.append(reference)
        return self.secret


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.reconciled: list[str] = []

    async def send(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        self.sent.append((secret, destination_reference, idempotency_key))
        return DeliveryOutcome.DELIVERED

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None:
        self.reconciled.append(idempotency_key)
        return DeliveryOutcome.UNKNOWN


def _composed(
    store: _FakeStore,
    channel: _FakeChannel,
) -> ComposedRecoverySecretDelivery:
    return ComposedRecoverySecretDelivery(store=store, channel=channel)


@pytest.mark.asyncio
async def test_publish_reads_stored_secret_and_forwards_same_key() -> None:
    store = _FakeStore(secret="stored-raw-secret")
    channel = _FakeChannel()

    outcome = await _composed(store, channel).publish(
        reference="ref://case/1",
        destination_reference="recover@example.test",
        idempotency_key="key-1",
    )

    assert outcome is DeliveryOutcome.DELIVERED
    assert store.reads == ["ref://case/1"]
    assert channel.sent == [("stored-raw-secret", "recover@example.test", "key-1")]


@pytest.mark.asyncio
async def test_stage_delegates_to_store() -> None:
    store = _FakeStore()
    channel = _FakeChannel()
    expires_at = datetime.now(UTC)

    staged = await _composed(store, channel).stage(
        case_id=_CASE_ID,
        generation=2,
        secret="candidate",
        expires_at=expires_at,
    )

    assert store.staged == [(_CASE_ID, 2, "candidate", expires_at)]
    assert staged.created is True


@pytest.mark.asyncio
async def test_discard_delegates_to_store() -> None:
    store = _FakeStore()
    channel = _FakeChannel()

    await _composed(store, channel).discard(case_id=_CASE_ID, generation=2)

    assert store.discarded == [(_CASE_ID, 2)]
    assert channel.sent == []


@pytest.mark.asyncio
async def test_reconcile_delegates_to_channel() -> None:
    store = _FakeStore()
    channel = _FakeChannel()

    outcome = await _composed(store, channel).reconcile(
        reference="ref://case/1",
        idempotency_key="key-2",
    )

    assert outcome is DeliveryOutcome.UNKNOWN
    assert channel.reconciled == ["key-2"]
    assert store.reads == []


def test_composite_structurally_satisfies_delivery_port() -> None:
    delivery: RecoverySecretDelivery = _composed(_FakeStore(), _FakeChannel())

    assert isinstance(delivery, ComposedRecoverySecretDelivery)
