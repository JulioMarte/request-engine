from datetime import UTC, datetime, timedelta
from typing import NoReturn, cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    RecoverySecretDelivery,
)
from request_engine.platform.secrets.delivery_worker import (
    PostgresRecoveryDeliveryLeaseStore,
    RecoveryDeliveryLease,
    RecoveryDeliveryProcessor,
)
from request_engine.platform.worker.runtime import (
    LeaseLostWorkError,
    PermanentWorkError,
    RetryableWorkError,
)

_CASE_ID = UUID("11111111-1111-1111-1111-111111111111")


class _FakeRecoveryDeliveryLeaseStore:
    def __init__(self, *, completion_result: bool = True) -> None:
        self.completion_result = completion_result
        self.completed: list[tuple[RecoveryDeliveryLease, str | None, str | None]] = []

    async def complete(
        self,
        lease: RecoveryDeliveryLease,
        *,
        outcome: str | None = None,
        error_class: str | None = None,
    ) -> bool:
        self.completed.append((lease, outcome, error_class))
        return self.completion_result


class _FakeRecoverySecretDelivery:
    def __init__(
        self,
        *,
        publish_outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED,
        reconcile_outcome: DeliveryOutcome | None = None,
        publish_error: Exception | None = None,
    ) -> None:
        self.publish_outcome = publish_outcome
        self.reconcile_outcome = reconcile_outcome
        self.publish_error = publish_error
        self.calls: list[tuple[str, str]] = []
        self.published: list[tuple[str, str, str]] = []
        self.reconciled: list[tuple[str, str]] = []

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        self.calls.append(("publish", idempotency_key))
        self.published.append((reference, destination_reference, idempotency_key))
        if self.publish_error is not None:
            raise self.publish_error
        return self.publish_outcome

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None:
        self.calls.append(("reconcile", idempotency_key))
        self.reconciled.append((reference, idempotency_key))
        return self.reconcile_outcome


def _processor(
    store: _FakeRecoveryDeliveryLeaseStore,
    delivery: _FakeRecoverySecretDelivery,
) -> RecoveryDeliveryProcessor:
    return RecoveryDeliveryProcessor(
        cast(PostgresRecoveryDeliveryLeaseStore, store),
        cast(RecoverySecretDelivery, delivery),
    )


def _lease(*, attempt_count: int = 1, generation: int = 3) -> RecoveryDeliveryLease:
    return RecoveryDeliveryLease(
        id=uuid4(),
        case_id=_CASE_ID,
        generation=generation,
        secret_reference="recovery-secret-reference",
        secret_digest="a" * 64,
        destination_reference="destination-reference",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        attempt_count=attempt_count,
        claim_token=uuid4(),
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_first_attempt_publishes_without_reconcile_and_completes_delivered() -> None:
    lease = _lease(attempt_count=1)
    delivery = _FakeRecoverySecretDelivery(publish_outcome=DeliveryOutcome.DELIVERED)
    store = _FakeRecoveryDeliveryLeaseStore()
    idempotency_key = f"{lease.case_id}:{lease.generation}"

    await _processor(store, delivery).process(lease)

    assert delivery.calls == [("publish", idempotency_key)]
    assert delivery.published == [
        (lease.secret_reference, lease.destination_reference, idempotency_key)
    ]
    assert delivery.reconciled == []
    assert store.completed == [(lease, "delivered", None)]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retry_attempt_reconciles_before_publish_and_finalizes_reconciled_outcome() -> None:
    lease = _lease(attempt_count=2)
    delivery = _FakeRecoverySecretDelivery(
        reconcile_outcome=DeliveryOutcome.DELIVERED,
        publish_outcome=DeliveryOutcome.FAILED,
    )
    store = _FakeRecoveryDeliveryLeaseStore()
    idempotency_key = f"{lease.case_id}:{lease.generation}"

    await _processor(store, delivery).process(lease)

    assert delivery.calls == [("reconcile", idempotency_key)]
    assert delivery.reconciled == [(lease.secret_reference, idempotency_key)]
    assert delivery.published == []
    assert store.completed == [(lease, "delivered", None)]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retry_attempt_publishes_when_reconcile_finds_no_outcome() -> None:
    lease = _lease(attempt_count=3)
    delivery = _FakeRecoverySecretDelivery(
        reconcile_outcome=None,
        publish_outcome=DeliveryOutcome.DELIVERED,
    )
    store = _FakeRecoveryDeliveryLeaseStore()
    idempotency_key = f"{lease.case_id}:{lease.generation}"

    await _processor(store, delivery).process(lease)

    assert delivery.calls == [
        ("reconcile", idempotency_key),
        ("publish", idempotency_key),
    ]
    assert store.completed == [(lease, "delivered", None)]


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    ("outcome", "expected_completion"),
    [
        (DeliveryOutcome.DELIVERED, ("delivered", None)),
        (DeliveryOutcome.UNKNOWN, ("unknown", "ambiguous_delivery_outcome")),
        (DeliveryOutcome.FAILED, ("failed", "provider_rejected")),
    ],
)
async def test_publish_outcome_maps_to_fenced_completion(
    outcome: DeliveryOutcome,
    expected_completion: tuple[str, str | None],
) -> None:
    lease = _lease()
    delivery = _FakeRecoverySecretDelivery(publish_outcome=outcome)
    store = _FakeRecoveryDeliveryLeaseStore()

    await _processor(store, delivery).process(lease)

    assert store.completed == [(lease, expected_completion[0], expected_completion[1])]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retryable_delivery_failure_propagates_as_retryable_work_error() -> None:
    lease = _lease()
    delivery = _FakeRecoverySecretDelivery(
        publish_error=RecoveryDeliveryRetryable("provider timeout"),
    )
    store = _FakeRecoveryDeliveryLeaseStore()

    with pytest.raises(RetryableWorkError) as excinfo:
        await _processor(store, delivery).process(lease)

    assert excinfo.value.error_class == "RecoveryDeliveryRetryable"
    assert isinstance(excinfo.value.__cause__, RecoveryDeliveryRetryable)
    assert store.completed == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_permanent_delivery_failure_propagates_as_permanent_work_error() -> None:
    lease = _lease()
    delivery = _FakeRecoverySecretDelivery(
        publish_error=RecoveryDeliveryPermanent("provider rejected"),
    )
    store = _FakeRecoveryDeliveryLeaseStore()

    with pytest.raises(PermanentWorkError) as excinfo:
        await _processor(store, delivery).process(lease)

    assert excinfo.value.error_class == "RecoveryDeliveryPermanent"
    assert isinstance(excinfo.value.__cause__, RecoveryDeliveryPermanent)
    assert store.completed == []


@pytest.mark.asyncio
@pytest.mark.unit
async def test_completion_fence_loss_raises_lease_lost_work_error() -> None:
    lease = _lease()
    delivery = _FakeRecoverySecretDelivery(publish_outcome=DeliveryOutcome.DELIVERED)
    store = _FakeRecoveryDeliveryLeaseStore(completion_result=False)

    with pytest.raises(LeaseLostWorkError, match="completion_fence_lost"):
        await _processor(store, delivery).process(lease)

    assert store.completed == [(lease, "delivered", None)]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_idempotency_key_is_exactly_case_id_and_generation() -> None:
    lease = _lease(attempt_count=2, generation=7)
    delivery = _FakeRecoverySecretDelivery(reconcile_outcome=None)
    store = _FakeRecoveryDeliveryLeaseStore()
    expected_key = "11111111-1111-1111-1111-111111111111:7"

    await _processor(store, delivery).process(lease)

    assert expected_key == f"{lease.case_id}:{lease.generation}"
    assert delivery.calls == [
        ("reconcile", expected_key),
        ("publish", expected_key),
    ]
    assert delivery.reconciled == [(lease.secret_reference, expected_key)]
    assert delivery.published == [
        (lease.secret_reference, lease.destination_reference, expected_key)
    ]


class _UnreachableSessionFactory:
    def __call__(self) -> NoReturn:
        raise AssertionError("session factory must not be opened before validation")


def _store() -> PostgresRecoveryDeliveryLeaseStore:
    return PostgresRecoveryDeliveryLeaseStore(cast(SessionFactory, _UnreachableSessionFactory()))


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    ("limit", "lease"),
    [
        (0, timedelta(seconds=60)),
        (101, timedelta(seconds=60)),
        (50, timedelta(0)),
        (50, timedelta(minutes=15, seconds=1)),
    ],
)
async def test_claim_rejects_invalid_limit_or_lease_before_sql(
    limit: int,
    lease: timedelta,
) -> None:
    with pytest.raises(ValueError):
        await _store().claim(limit=limit, lease=lease)


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    "delay",
    [timedelta(seconds=-1), timedelta(days=1, seconds=1)],
)
async def test_retry_after_rejects_out_of_range_delay_before_sql(delay: timedelta) -> None:
    with pytest.raises(ValueError):
        await _store().retry_after(_lease(), delay=delay, error_class="provider_timeout")


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    "extension",
    [timedelta(0), timedelta(seconds=-1), timedelta(minutes=15, seconds=1)],
)
async def test_renew_rejects_invalid_extension_before_sql(extension: timedelta) -> None:
    with pytest.raises(ValueError):
        await _store().renew(_lease(), extension=extension)
