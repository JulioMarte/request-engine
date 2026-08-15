import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.errors import ProviderEventDedupeConflict


@dataclass(frozen=True, slots=True)
class ProviderEventReceipt:
    id: UUID
    replay: bool
    payload_hash: str


@dataclass(frozen=True, slots=True)
class ProviderEventLease:
    id: UUID
    organization_id: UUID
    claim_token: UUID
    provider_key: str
    connection_key: str
    provider_event_id: str
    payload_hash: str
    payload: dict[str, object]
    attempt_count: int
    lease_until: datetime


async def record_provider_event(
    session: AsyncSession,
    *,
    organization_id: UUID,
    provider_key: str,
    connection_key: str,
    provider_event_id: str,
    payload: dict[str, object],
) -> ProviderEventReceipt:
    """Persist one inbound provider event before any business interpretation."""

    if not provider_key or not connection_key or not provider_event_id:
        raise ValueError("provider_key, connection_key and provider_event_id are required")
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO request_engine.provider_events (
                    organization_id, provider_key, connection_key,
                    provider_event_id, payload_hash, payload
                ) VALUES (
                    :organization_id, :provider_key, :connection_key,
                    :provider_event_id, :payload_hash, CAST(:payload AS jsonb)
                )
                ON CONFLICT (
                    organization_id, provider_key, connection_key, provider_event_id
                ) DO NOTHING
                RETURNING id
                """
            ),
            {
                "organization_id": organization_id,
                "provider_key": provider_key,
                "connection_key": connection_key,
                "provider_event_id": provider_event_id,
                "payload_hash": payload_hash,
                "payload": payload_json,
            },
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return ProviderEventReceipt(cast(UUID, inserted), False, payload_hash)

    existing = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, payload_hash
                    FROM request_engine.provider_events
                    WHERE organization_id = :organization_id
                      AND provider_key = :provider_key
                      AND connection_key = :connection_key
                      AND provider_event_id = :provider_event_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "provider_key": provider_key,
                    "connection_key": connection_key,
                    "provider_event_id": provider_event_id,
                },
            )
        )
        .mappings()
        .one()
    )
    if cast(str, existing["payload_hash"]) != payload_hash:
        raise ProviderEventDedupeConflict(provider_key, connection_key, provider_event_id)
    return ProviderEventReceipt(cast(UUID, existing["id"]), True, payload_hash)


class PostgresProviderEventWorker:
    """Fenced cross-tenant ProviderEvent lease store."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def claim(
        self,
        *,
        limit: int = 50,
        lease: timedelta = timedelta(seconds=60),
    ) -> tuple[ProviderEventLease, ...]:
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
                            SELECT provider_event_row_id, organization_id, claim_token,
                                   provider_key, connection_key, provider_event_id,
                                   payload_hash, payload, attempt_count, lease_until
                            FROM request_cmd.claim_provider_events(
                                :limit, make_interval(secs => :lease_seconds)
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
            ProviderEventLease(
                id=cast(UUID, row["provider_event_row_id"]),
                organization_id=cast(UUID, row["organization_id"]),
                claim_token=cast(UUID, row["claim_token"]),
                provider_key=cast(str, row["provider_key"]),
                connection_key=cast(str, row["connection_key"]),
                provider_event_id=cast(str, row["provider_event_id"]),
                payload_hash=cast(str, row["payload_hash"]),
                payload=cast(dict[str, object], row["payload"]),
                attempt_count=cast(int, row["attempt_count"]),
                lease_until=cast(datetime, row["lease_until"]),
            )
            for row in rows
        )

    async def complete(self, lease: ProviderEventLease) -> bool:
        return await self._boolean_call(
            "SELECT request_cmd.complete_provider_event(:id, :token)", lease
        )

    async def dead_letter(self, lease: ProviderEventLease, *, error_class: str) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.dead_letter_provider_event(
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

    async def reject(self, lease: ProviderEventLease, *, error_class: str) -> bool:
        async with self._session_factory() as session, session.begin():
            return cast(
                bool,
                (
                    await session.execute(
                        text(
                            """
                            SELECT request_cmd.reject_provider_event(
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

    async def retry_after(
        self,
        lease: ProviderEventLease,
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
                            SELECT request_cmd.retry_provider_event_after(
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

    async def renew(self, lease: ProviderEventLease, *, extension: timedelta) -> bool:
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
                            SELECT request_cmd.renew_provider_event_lease(
                                :id, :token, make_interval(secs => :seconds)
                            )
                            """
                        ),
                        {"id": lease.id, "token": lease.claim_token, "seconds": seconds},
                    )
                ).scalar_one(),
            )

    async def _boolean_call(self, sql: str, lease: ProviderEventLease) -> bool:
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
