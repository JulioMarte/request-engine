from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from request_engine.platform.scheduling.postgres import ScheduledActionLease


class ScheduledActionDisposition(StrEnum):
    COMPLETED = "completed"
    DEFERRED = "deferred"
    DEAD = "dead"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ScheduledActionProcessResult:
    disposition: ScheduledActionDisposition
    detail: str


class ScheduledActionLeaseStore(Protocol):
    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[ScheduledActionLease, ...]: ...

    async def complete(self, lease: ScheduledActionLease) -> bool: ...

    async def retry(
        self,
        lease: ScheduledActionLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str: ...

    async def dead_letter(self, lease: ScheduledActionLease, *, error_class: str) -> bool: ...


class ScheduledActionProcessor(Protocol):
    async def process(self, lease: ScheduledActionLease) -> ScheduledActionProcessResult: ...


def retry_delay(attempt_count: int) -> timedelta:
    """Bound technical retries so poison work converges to the DB max-attempts policy."""

    normalized_attempt = max(1, attempt_count)
    return timedelta(seconds=min(300, 5 * (2 ** min(normalized_attempt - 1, 6))))
