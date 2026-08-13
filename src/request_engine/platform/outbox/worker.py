from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class OutboxMessageLease:
    id: UUID
    organization_id: UUID
    claim_token: UUID
    event_type: str
    schema_version: int
    aggregate_kind: str
    aggregate_id: UUID
    payload: dict[str, object]
    attempt_count: int
    lease_until: datetime


class PostgresOutboxWorker:
    """Fenced cross-tenant worker surface for durable outbox facts."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[OutboxMessageLease, ...]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        lease_seconds = _lease_seconds(lease)
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT message_id, organization_id, claim_token,
                                   event_type, schema_version, aggregate_kind,
                                   aggregate_id, payload, attempt_count, lease_until
                            FROM request_cmd.claim_outbox_messages(
                                :limit,
                                make_interval(secs => :lease_seconds)
                            )
                            """
                        ),
                        {"limit": limit, "lease_seconds": lease_seconds},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            OutboxMessageLease(
                id=cast(UUID, row["message_id"]),
                organization_id=cast(UUID, row["organization_id"]),
                claim_token=cast(UUID, row["claim_token"]),
                event_type=cast(str, row["event_type"]),
                schema_version=cast(int, row["schema_version"]),
                aggregate_kind=cast(str, row["aggregate_kind"]),
                aggregate_id=cast(UUID, row["aggregate_id"]),
                payload=cast(dict[str, object], row["payload"]),
                attempt_count=cast(int, row["attempt_count"]),
                lease_until=cast(datetime, row["lease_until"]),
            )
            for row in rows
        )

    async def complete(self, lease: OutboxMessageLease) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text("SELECT request_cmd.complete_outbox_message(:id, :token)"),
                        {"id": lease.id, "token": lease.claim_token},
                    )
                ).scalar_one(),
            )

    async def retry(
        self,
        lease: OutboxMessageLease,
        *,
        next_attempt_at: datetime,
        error_class: str,
    ) -> str:
        async with self._session_factory() as session, session.begin():
            return cast(
                str,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.retry_outbox_message(
                                :id, :token, :next_attempt_at, :error_class
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "next_attempt_at": next_attempt_at,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def mark_failed(self, lease: OutboxMessageLease, *, error_class: str) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.dead_letter_outbox_message(
                                :id, :token, :error_class
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )


def _lease_seconds(value: timedelta) -> float:
    seconds = value.total_seconds()
    if seconds <= 0 or seconds > 900:
        raise ValueError("lease must be > 0 and <= 15 minutes")
    return seconds
