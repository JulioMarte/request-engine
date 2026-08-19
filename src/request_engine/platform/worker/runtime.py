import asyncio
import hashlib
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class WorkLease(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def attempt_count(self) -> int: ...


class LeaseStore[TLease: WorkLease](Protocol):
    async def claim(self, *, limit: int, lease: timedelta) -> tuple[TLease, ...]: ...

    async def complete(self, lease: TLease) -> bool: ...

    async def retry_after(
        self,
        lease: TLease,
        *,
        delay: timedelta,
        error_class: str,
    ) -> str: ...

    async def dead_letter(self, lease: TLease, *, error_class: str) -> bool: ...

    async def renew(self, lease: TLease, *, extension: timedelta) -> bool: ...


class LeaseProcessor[TLease: WorkLease](Protocol):
    async def process(self, lease: TLease) -> None: ...


class LeaseRejecter[TLease: WorkLease](Protocol):
    async def __call__(self, lease: TLease, *, error_class: str) -> bool: ...


class RetryableWorkError(RuntimeError):
    def __init__(self, error_class: str, message: str | None = None) -> None:
        self.error_class = error_class
        super().__init__(message or error_class)


class PermanentWorkError(RuntimeError):
    def __init__(self, error_class: str, message: str | None = None) -> None:
        self.error_class = error_class
        super().__init__(message or error_class)


class RejectedWorkError(RuntimeError):
    """Signal a semantically invalid event that must not consume retry budget."""

    def __init__(self, error_class: str, message: str | None = None) -> None:
        self.error_class = error_class
        super().__init__(message or error_class)


class LeaseLostWorkError(RuntimeError):
    """Signal that processing lost its fencing token and must not finalize work."""


class WorkerItemState(StrEnum):
    COMPLETED = "completed"
    RETRY = "retry"
    DEAD = "dead"
    REJECTED = "rejected"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class WorkerItemOutcome:
    work_id: UUID
    state: WorkerItemState
    detail: str


@dataclass(frozen=True, slots=True)
class WorkerRuntimeConfig:
    max_concurrency: int = 8
    claim_batch_size: int = 8
    lease_duration: timedelta = timedelta(seconds=60)
    heartbeat_interval: timedelta = timedelta(seconds=20)
    processing_timeout: timedelta = timedelta(minutes=5)
    idle_sleep: timedelta = timedelta(milliseconds=500)
    retry_base: timedelta = timedelta(seconds=5)
    retry_cap: timedelta = timedelta(minutes=5)
    retry_jitter_fraction: float = 0.2

    def __post_init__(self) -> None:
        if self.max_concurrency <= 0 or self.max_concurrency > 500:
            raise ValueError("max_concurrency must be between 1 and 500")
        if self.claim_batch_size <= 0 or self.claim_batch_size > 500:
            raise ValueError("claim_batch_size must be between 1 and 500")
        if self.lease_duration <= timedelta(0) or self.lease_duration > timedelta(minutes=15):
            raise ValueError("lease_duration must be > 0 and <= 15 minutes")
        if self.heartbeat_interval <= timedelta(0):
            raise ValueError("heartbeat_interval must be positive")
        if self.heartbeat_interval >= self.lease_duration:
            raise ValueError("heartbeat_interval must be shorter than lease_duration")
        if self.processing_timeout <= timedelta(0) or self.processing_timeout > timedelta(hours=24):
            raise ValueError("processing_timeout must be > 0 and <= 24 hours")
        if self.idle_sleep <= timedelta(0) or self.idle_sleep > timedelta(seconds=60):
            raise ValueError("idle_sleep must be > 0 and <= 60 seconds")
        if self.retry_base < timedelta(0) or self.retry_cap < self.retry_base:
            raise ValueError("retry bounds are invalid")
        if not 0.0 <= self.retry_jitter_fraction <= 0.5:
            raise ValueError("retry_jitter_fraction must be between 0.0 and 0.5")


class FencedWorkerRuntime[TLease: WorkLease]:
    """Bounded lease runner with heartbeat, fencing, retry, and backpressure.

    A batch never claims more rows than can execute concurrently. If heartbeat
    renewal loses the claim token, the runtime does not finalize that lease;
    the new owner is authoritative and must replay the idempotent work.

    Processing is bounded by ``processing_timeout``. Processors must remain
    cancellation-safe and provider/network timeouts should be shorter than the
    runtime timeout so a live process cannot renew one lease indefinitely.
    """

    def __init__(
        self,
        store: LeaseStore[TLease],
        processor: LeaseProcessor[TLease],
        *,
        rejecter: LeaseRejecter[TLease] | None = None,
        config: WorkerRuntimeConfig | None = None,
    ) -> None:
        self._store = store
        self._processor = processor
        self._rejecter = rejecter
        self._config = config or WorkerRuntimeConfig()

    async def run_once(self) -> tuple[WorkerItemOutcome, ...]:
        limit = min(self._config.claim_batch_size, self._config.max_concurrency)
        leases = await self._store.claim(limit=limit, lease=self._config.lease_duration)
        if not leases:
            return ()
        outcomes = await asyncio.gather(*(self._process_one(lease) for lease in leases))
        return tuple(outcomes)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            outcomes = await self.run_once()
            if outcomes:
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._config.idle_sleep.total_seconds()
                )

    async def _process_one(self, lease: TLease) -> WorkerItemOutcome:
        stop_heartbeat = asyncio.Event()
        lost_lease = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(lease, stop_heartbeat=stop_heartbeat, lost_lease=lost_lease)
        )
        failure: Exception | None = None
        try:
            async with asyncio.timeout(self._config.processing_timeout.total_seconds()):
                await self._processor.process(lease)
        except TimeoutError:
            failure = RetryableWorkError("processing_timeout")
        except Exception as exc:
            failure = exc
        finally:
            stop_heartbeat.set()
            await heartbeat

        if lost_lease.is_set() or isinstance(failure, LeaseLostWorkError):
            return WorkerItemOutcome(lease.id, WorkerItemState.STALE, "lease_lost")

        if failure is None:
            completed = await self._store.complete(lease)
            return WorkerItemOutcome(
                lease.id,
                WorkerItemState.COMPLETED if completed else WorkerItemState.STALE,
                "completed" if completed else "completion_fence_lost",
            )

        if isinstance(failure, RejectedWorkError):
            if self._rejecter is None:
                raise RuntimeError("processor requested rejection without a rejecter") from failure
            rejected = await self._rejecter(lease, error_class=failure.error_class)
            return WorkerItemOutcome(
                lease.id,
                WorkerItemState.REJECTED if rejected else WorkerItemState.STALE,
                failure.error_class if rejected else "rejection_fence_lost",
            )

        if isinstance(failure, PermanentWorkError):
            dead = await self._store.dead_letter(lease, error_class=failure.error_class)
            return WorkerItemOutcome(
                lease.id,
                WorkerItemState.DEAD if dead else WorkerItemState.STALE,
                failure.error_class if dead else "dead_letter_fence_lost",
            )

        error_class = (
            failure.error_class
            if isinstance(failure, RetryableWorkError)
            else f"unexpected_{type(failure).__name__}"
        )
        retry_state = await self._store.retry_after(
            lease,
            delay=self._retry_delay(lease),
            error_class=error_class,
        )
        if retry_state == "stale":
            return WorkerItemOutcome(lease.id, WorkerItemState.STALE, "retry_fence_lost")
        if retry_state == "dead":
            return WorkerItemOutcome(lease.id, WorkerItemState.DEAD, error_class)
        return WorkerItemOutcome(lease.id, WorkerItemState.RETRY, error_class)

    async def _heartbeat(
        self,
        lease: TLease,
        *,
        stop_heartbeat: asyncio.Event,
        lost_lease: asyncio.Event,
    ) -> None:
        interval = self._config.heartbeat_interval.total_seconds()
        while True:
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                return
            except TimeoutError:
                try:
                    renewed = await self._store.renew(
                        lease,
                        extension=self._config.lease_duration,
                    )
                except Exception:
                    # If the runtime cannot prove lease ownership, it must stop
                    # finalization and let the durable lease expire/reclaim.
                    lost_lease.set()
                    return
                if not renewed:
                    lost_lease.set()
                    return

    def _retry_delay(self, lease: TLease) -> timedelta:
        exponent = max(0, min(lease.attempt_count - 1, 20))
        base_seconds = self._config.retry_base.total_seconds()
        cap_seconds = self._config.retry_cap.total_seconds()
        bounded_seconds = min(base_seconds * (2**exponent), cap_seconds)
        jitter = self._config.retry_jitter_fraction
        if jitter == 0.0 or bounded_seconds == 0.0:
            return timedelta(seconds=bounded_seconds)

        digest = hashlib.blake2b(
            f"{lease.id}:{lease.attempt_count}".encode(), digest_size=8
        ).digest()
        unit = int.from_bytes(digest, "big") / ((1 << 64) - 1)
        factor = (1.0 - jitter) + (2.0 * jitter * unit)
        return timedelta(seconds=min(bounded_seconds * factor, cap_seconds))
