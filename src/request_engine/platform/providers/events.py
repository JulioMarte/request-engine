import hashlib
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.store import schedule_action


@dataclass(frozen=True, slots=True)
class VerifiedProviderConnection:
    """Trusted provider-connection identity resolved by an authenticated adapter."""

    organization_id: UUID
    provider_key: str
    connection_key: str


@dataclass(frozen=True, slots=True)
class ProviderEventReceipt:
    id: UUID
    replay: bool


class ProviderEventPayloadMismatch(Exception):
    def __init__(self, provider_event_id: str) -> None:
        super().__init__("provider event id was reused with a different payload")
        self.provider_event_id = provider_event_id


class PostgresProviderEventIngress:
    """Durably ingest one already-authenticated provider callback."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        connection: VerifiedProviderConnection,
        *,
        provider_event_id: str,
        payload: dict[str, object],
    ) -> ProviderEventReceipt:
        if not connection.provider_key or not connection.connection_key:
            raise ValueError("provider_key and connection_key are required")
        if not provider_event_id:
            raise ValueError("provider_event_id is required")

        canonical_payload = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

        async with tenant_transaction(
            self._session_factory,
            connection.organization_id,
        ) as session:
            inserted = (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.provider_events (
                            organization_id,
                            provider_key,
                            connection_key,
                            provider_event_id,
                            payload_hash,
                            payload
                        ) VALUES (
                            :organization_id,
                            :provider_key,
                            :connection_key,
                            :provider_event_id,
                            :payload_hash,
                            CAST(:payload AS jsonb)
                        )
                        ON CONFLICT (
                            organization_id,
                            provider_key,
                            connection_key,
                            provider_event_id
                        ) DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "organization_id": connection.organization_id,
                        "provider_key": connection.provider_key,
                        "connection_key": connection.connection_key,
                        "provider_event_id": provider_event_id,
                        "payload_hash": payload_hash,
                        "payload": canonical_payload,
                    },
                )
            ).scalar_one_or_none()

            if inserted is not None:
                event_id = cast(UUID, inserted)
                await schedule_action(
                    session,
                    organization_id=connection.organization_id,
                    owner_module="provider_events",
                    action_type="process_event",
                    action_version=1,
                    subject_kind="ProviderEvent",
                    subject_id=event_id,
                    dedupe_key=f"provider-event:process:{event_id}",
                    execute_at=(
                        await session.execute(text("SELECT clock_timestamp()"))
                    ).scalar_one(),
                    payload={"provider_event_id": str(event_id)},
                )
                return ProviderEventReceipt(id=event_id, replay=False)

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
                            "organization_id": connection.organization_id,
                            "provider_key": connection.provider_key,
                            "connection_key": connection.connection_key,
                            "provider_event_id": provider_event_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            if cast(str, existing["payload_hash"]) != payload_hash:
                raise ProviderEventPayloadMismatch(provider_event_id)
            return ProviderEventReceipt(id=cast(UUID, existing["id"]), replay=True)
