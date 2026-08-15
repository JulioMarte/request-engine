import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class OutboxMessageLease:
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


async def append_outbox(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    aggregate_kind: str,
    aggregate_id: UUID,
    payload: dict[str, object],
    schema_version: int = 1,
) -> None:
    """Append one after-commit integration fact inside the authoritative transaction."""

    if not event_type or schema_version <= 0:
        raise ValueError("event_type is required and schema_version must be positive")

    await session.execute(
        text(
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id,
                event_type,
                schema_version,
                aggregate_kind,
                aggregate_id,
                payload
            ) VALUES (
                :organization_id,
                :event_type,
                :schema_version,
                :aggregate_kind,
                :aggregate_id,
                CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "event_type": event_type,
            "schema_version": schema_version,
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "payload": json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")),
        },
    )


class PostgresOutboxWorker:
    """Fenced cross-tenant outbox claim/completion surface for worker processes."""

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
            OutboxMessageLease(
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

    async def complete(self, lease: OutboxMessageLease) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.complete_outbox_message(
                                :message_id, :claim_token
                            )
                            """
                        ),
                        {"message_id": lease.id, "claim_token": lease.claim_token},
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
                                :message_id,
                                :claim_token,
                                :next_attempt_at,
                                :error_class
                            )
                            """
                        ),
                        {
                            "message_id": lease.id,
                            "claim_token": lease.claim_token,
                            "next_attempt_at": next_attempt_at,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def dead_letter(self, lease: OutboxMessageLease, *, error_class: str) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.dead_letter_outbox_message(
                                :message_id, :claim_token, :error_class
                            )
                            """
                        ),
                        {
                            "message_id": lease.id,
                            "claim_token": lease.claim_token,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def replay(
        self,
        message_id: UUID,
        *,
        next_attempt_at: datetime,
        reason: str,
    ) -> bool:
        """Admin-only manual replay of a terminal outbox message."""

        if not reason.strip():
            raise ValueError("reason is required for auditable replay")
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.replay_outbox_message(
                                :message_id, :next_attempt_at, :reason
                            )
                            """
                        ),
                        {
                            "message_id": message_id,
                            "next_attempt_at": next_attempt_at,
                            "reason": reason,
                        },
                    )
                ).scalar_one(),
            )
