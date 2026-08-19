from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class OutboxLease:
    id: UUID
    organization_id: UUID
    claim_token: UUID
    event_type: str
    schema_version: int
    aggregate_kind: str | None
    aggregate_id: UUID | None
    payload: dict[str, object]
    attempt_count: int
    lease_until: datetime


class PostgresOutboxWorker:
    """Fenced cross-tenant OutboxMessage lease store."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[OutboxLease, ...]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        lease_seconds = lease.total_seconds()
        if lease_seconds <= 0 or lease_seconds > 900:
            raise ValueError("lease must be > 0 and <= 15 minutes")
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
            OutboxLease(
                id=cast(UUID, row["message_id"]),
                organization_id=cast(UUID, row["organization_id"]),
                claim_token=cast(UUID, row["claim_token"]),
                event_type=cast(str, row["event_type"]),
                schema_version=cast(int, row["schema_version"]),
                aggregate_kind=cast(str | None, row["aggregate_kind"]),
                aggregate_id=cast(UUID | None, row["aggregate_id"]),
                payload=cast(dict[str, object], row["payload"]),
                attempt_count=cast(int, row["attempt_count"]),
                lease_until=cast(datetime, row["lease_until"]),
            )
            for row in rows
        )

    async def complete(self, lease: OutboxLease) -> bool:
        return await self._boolean_call(
            "SELECT request_cmd.complete_outbox_message(:id, :token)", lease
        )

    async def dead_letter(self, lease: OutboxLease, *, error_class: str) -> bool:
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
                        {"id": lease.id, "token": lease.claim_token, "error_class": error_class},
                    )
                ).scalar_one(),
            )

    async def retry_after(
        self,
        lease: OutboxLease,
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
                            SELECT request_cmd.retry_outbox_message_after(
                                :id, :token, make_interval(secs => :seconds), :error_class
                            )
                            """
                        ),
                        {
                            "id": lease.id,
                            "token": lease.claim_token,
                            "seconds": seconds,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def renew(self, lease: OutboxLease, *, extension: timedelta) -> bool:
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
                            SELECT request_cmd.renew_outbox_message_lease(
                                :id, :token, make_interval(secs => :seconds)
                            )
                            """
                        ),
                        {"id": lease.id, "token": lease.claim_token, "seconds": seconds},
                    )
                ).scalar_one(),
            )

    async def _boolean_call(self, sql: str, lease: OutboxLease) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(sql),
                        {"id": lease.id, "token": lease.claim_token},
                    )
                ).scalar_one(),
            )
