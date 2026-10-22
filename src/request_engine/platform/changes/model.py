"""Technical value types of the invalidation-only change feed (ADR 0020).

A change event says *that* something an authorized client may display changed;
it never carries business or personal payload. Clients re-read through owner
reads. These types are transport-neutral and Pydantic-free.
"""

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

_SNAPSHOT_RE = re.compile(r"^[0-9]{1,20}:[0-9]{1,20}:(?:[0-9]{1,20}(?:,[0-9]{1,20})*)?$")
_CURSOR_VERSION = "1"
_MAX_CURSOR_LENGTH = 4096


@dataclass(frozen=True, slots=True)
class FeedRow:
    """One committed outbox fact projected by ``request_read.change_feed_v1``."""

    event_id: UUID
    event_type: str
    aggregate_kind: str | None
    aggregate_id: UUID | None
    change_xid: int
    occurred_at: datetime
    queue_id: UUID | None
    location_id: UUID | None
    business_date: date | None
    reservation_id: UUID | None


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    """The exact, PII-free ``data`` of one ``change`` event for one topic."""

    topic: str
    kind: str
    resource_type: str
    resource_id: UUID
    queue_id: UUID | None
    location_id: UUID | None
    business_date: date | None
    occurred_at: datetime

    def data(self) -> dict[str, object]:
        occurred = self.occurred_at.astimezone(UTC)
        return {
            "topic": self.topic,
            "kind": self.kind,
            "resource_type": self.resource_type,
            "resource_id": str(self.resource_id),
            "scope": {
                "queue_id": None if self.queue_id is None else str(self.queue_id),
                "location_id": None if self.location_id is None else str(self.location_id),
                "business_date": (
                    None if self.business_date is None else self.business_date.isoformat()
                ),
            },
            "occurred_at": occurred.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """A PostgreSQL ``pg_snapshot`` plus the instant it was taken.

    Every fact whose ``change_xid`` is visible in the snapshot committed before
    it was taken; replay from a snapshot returns exactly the facts that were not.
    """

    snapshot: str
    taken_at: datetime

    def __post_init__(self) -> None:
        if _SNAPSHOT_RE.fullmatch(self.snapshot) is None:
            raise ValueError("malformed pg_snapshot")

    def cursor(self) -> str:
        encoded = base64.urlsafe_b64encode(self.snapshot.encode("ascii")).decode("ascii")
        issued_ms = int(self.taken_at.timestamp() * 1000)
        return f"{_CURSOR_VERSION}.{issued_ms}.{encoded.rstrip('=')}"


def parse_cursor(value: str) -> FeedSnapshot | None:
    """Decode an opaque ``Last-Event-ID``; ``None`` means unknown (client must reset)."""

    if not value or len(value) > _MAX_CURSOR_LENGTH:
        return None
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != _CURSOR_VERSION or not parts[1].isdigit():
        return None
    try:
        padded = parts[2] + "=" * (-len(parts[2]) % 4)
        snapshot = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
        taken_at = datetime.fromtimestamp(int(parts[1]) / 1000, tz=UTC)
        return FeedSnapshot(snapshot=snapshot, taken_at=taken_at)
    except (ValueError, UnicodeError, binascii.Error, OverflowError, OSError):
        return None


@dataclass(frozen=True, slots=True)
class ChangeItem:
    event: ChangeEvent
    cursor: str


@dataclass(frozen=True, slots=True)
class ResetItem:
    """The client may have missed changes and must refetch what it shows."""


StreamItem = ChangeItem | ResetItem
