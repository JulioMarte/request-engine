from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class ScheduledActionLease:
    id: UUID
    organization_id: UUID
    claim_token: UUID
    owner_module: str
    action_type: str
    action_version: int
    subject_kind: str | None
    subject_id: UUID | None
    payload: dict[str, object]
    attempt_count: int
    lease_until: datetime


class PostgresScheduledActionWorker:
    """Narrow wrapper around the fenced cross-tenant scheduler claim surface."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[ScheduledActionLease, ...]:
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
                            SELECT action_id, organization_id, claim_token,
                                   owner_module, action_type, action_version,
                                   subject_kind, subject_id, payload,
                                   attempt_count, lease_until
                            FROM request_cmd.claim_scheduled_actions(
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
            ScheduledActionLease(
                id=cast(UUID, row["action_id"]),
                organization_id=cast(UUID, row["organization_id"]),
                claim_token=cast(UUID, row["claim_token"]),
                owner_module=cast(str, row["owner_module"]),
                action_type=cast(str, row["action_type"]),
                action_version=cast(int, row["action_version"]),
                subject_kind=cast(str | None, row["subject_kind"]),
                subject_id=cast(UUID | None, row["subject_id"]),
                payload=cast(dict[str, object], row["payload"]),
                attempt_count=cast(int, row["attempt_count"]),
                lease_until=cast(datetime, row["lease_until"]),
            )
            for row in rows
        )

    async def complete(self, lease: ScheduledActionLease) -> bool:
        return await self._finish_boolean(
            "SELECT request_cmd.complete_scheduled_action(:action_id, :claim_token)",
            lease,
        )

    async def dead_letter(self, lease: ScheduledActionLease, *, error_class: str) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.dead_letter_scheduled_action(
                                :action_id, :claim_token, :error_class
                            )
                            """
                        ),
                        {
                            "action_id": lease.id,
                            "claim_token": lease.claim_token,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def retry(
        self,
        lease: ScheduledActionLease,
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
                            SELECT request_cmd.retry_scheduled_action(
                                :action_id,
                                :claim_token,
                                :next_attempt_at,
                                :error_class
                            )
                            """
                        ),
                        {
                            "action_id": lease.id,
                            "claim_token": lease.claim_token,
                            "next_attempt_at": next_attempt_at,
                            "error_class": error_class,
                        },
                    )
                ).scalar_one(),
            )

    async def _finish_boolean(self, query: str, lease: ScheduledActionLease) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(query),
                        {"action_id": lease.id, "claim_token": lease.claim_token},
                    )
                ).scalar_one(),
            )
