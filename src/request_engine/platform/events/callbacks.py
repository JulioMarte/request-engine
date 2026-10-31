from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Request

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.provider_events import (
    ProviderEventReceipt,
    record_provider_event,
)


@dataclass(frozen=True, slots=True)
class TrustedProviderCallbackContext:
    """Authority derived by a deployment authentication adapter.

    None of these values may be accepted from the provider callback payload.
    They identify the already-authenticated provider connection whose event is
    being recorded.
    """

    organization_id: UUID
    provider_key: str
    connection_key: str


class ProviderCallbackAuthenticationFailed(Exception):
    """The callback is not authenticated; the reason stays server-side only."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProviderCallbackAuthenticator(Protocol):
    """Authenticate one inbound provider callback and bind its trusted connection.

    Implementations raise ProviderCallbackAuthenticationFailed for any
    credential failure so the HTTP surface answers one uniform 401.
    """

    async def authenticate_callback(self, request: Request) -> TrustedProviderCallbackContext: ...


async def ingest_provider_callback(
    session_factory: SessionFactory,
    authenticator: ProviderCallbackAuthenticator,
    request: Request,
    *,
    provider_event_id: str,
    payload: dict[str, object],
) -> ProviderEventReceipt:
    """Persist an authenticated provider fact before semantic interpretation.

    The external body contributes only the provider's event identity and raw
    payload. Tenant/provider/connection authority comes exclusively from the
    authentication adapter. Business aggregates are intentionally not mutated
    at this boundary; a fenced ProviderEvent worker performs later semantic
    interpretation through module-owned commands.
    """

    trusted = await authenticator.authenticate_callback(request)
    return await record_authenticated_provider_callback(
        session_factory,
        trusted,
        provider_event_id=provider_event_id,
        payload=payload,
    )


async def record_authenticated_provider_callback(
    session_factory: SessionFactory,
    trusted: TrustedProviderCallbackContext,
    *,
    provider_event_id: str,
    payload: dict[str, object],
) -> ProviderEventReceipt:
    """Persist one callback whose connection authority was already derived.

    Lets an HTTP surface authenticate over the raw body before it parses the
    body for the event identity, without a second persistence path.
    """

    if not trusted.provider_key or not trusted.connection_key:
        raise ValueError(
            "authenticated provider callback context must name provider and connection"
        )

    async with tenant_transaction(session_factory, trusted.organization_id) as session:
        return await record_provider_event(
            session,
            organization_id=trusted.organization_id,
            provider_key=trusted.provider_key,
            connection_key=trusted.connection_key,
            provider_event_id=provider_event_id,
            payload=payload,
        )
