"""HMAC authentication for inbound provider-event callbacks.

The callback credential is a per-connection key derived server-side from one
deployment master secret::

    connection_key = HMAC-SHA256(master, "request-engine.provider-callback.v1\\n"
                                         "<organization_id>\\n<provider_key>\\n<connection_key>")

The caller names the organization in a header and the provider/connection in
the path, but those names are only *key selectors*: the request verifies only
when signed with the key derived for exactly that organization + provider +
connection triple. The body never contributes authority. The signature covers
the timestamp and the raw body, and the timestamp must lie inside a bounded
skew window; a replay inside the window is absorbed by ProviderEvent dedupe.
"""

import hashlib
import hmac
import logging
import time
from collections.abc import Callable, Collection
from uuid import UUID

from fastapi import Request

from request_engine.platform.events.callbacks import (
    ProviderCallbackAuthenticationFailed,
    TrustedProviderCallbackContext,
)

ORGANIZATION_HEADER = "X-Request-Engine-Organization"
TIMESTAMP_HEADER = "X-Request-Engine-Timestamp"
SIGNATURE_HEADER = "X-Request-Engine-Signature"
SIGNATURE_SCHEME = "v1"
MIN_MASTER_SECRET_BYTES = 32
_KEY_DERIVATION_LABEL = "request-engine.provider-callback.v1"

logger = logging.getLogger(__name__)


def derive_callback_key(
    master_secret: bytes,
    *,
    organization_id: UUID,
    provider_key: str,
    connection_key: str,
) -> bytes:
    material = f"{_KEY_DERIVATION_LABEL}\n{organization_id}\n{provider_key}\n{connection_key}"
    return hmac.new(master_secret, material.encode("utf-8"), hashlib.sha256).digest()


def callback_signature(callback_key: bytes, *, timestamp: int, body: bytes) -> str:
    signed = f"{SIGNATURE_SCHEME}\n{timestamp}\n".encode() + body
    return f"{SIGNATURE_SCHEME}={hmac.new(callback_key, signed, hashlib.sha256).hexdigest()}"


class HmacProviderCallbackAuthenticator:
    """ProviderCallbackAuthenticator bound to the deployment's registered connections."""

    def __init__(
        self,
        master_secret: bytes,
        *,
        connections: Collection[tuple[str, str]],
        max_skew_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(master_secret) < MIN_MASTER_SECRET_BYTES:
            raise ValueError("the provider callback secret must contain at least 32 bytes")
        if not connections:
            raise ValueError("at least one provider callback connection must be registered")
        if not 1 <= max_skew_seconds <= 900:
            raise ValueError("provider callback skew window must be 1..900 seconds")
        self._master_secret = master_secret
        self._connections = frozenset(connections)
        self._max_skew_seconds = max_skew_seconds
        self._clock = clock

    async def authenticate_callback(self, request: Request) -> TrustedProviderCallbackContext:
        try:
            return await self._authenticate(request)
        except ProviderCallbackAuthenticationFailed as exc:
            logger.warning("provider_callback_rejected", extra={"reason": exc.reason})
            raise

    async def _authenticate(self, request: Request) -> TrustedProviderCallbackContext:
        provider_key = str(request.path_params.get("provider_key", ""))
        connection_key = str(request.path_params.get("connection_key", ""))
        if (provider_key, connection_key) not in self._connections:
            raise ProviderCallbackAuthenticationFailed("unregistered_connection")
        organization_id = _organization(request.headers.get(ORGANIZATION_HEADER))
        timestamp = _timestamp(request.headers.get(TIMESTAMP_HEADER))
        if abs(self._clock() - timestamp) > self._max_skew_seconds:
            raise ProviderCallbackAuthenticationFailed("timestamp_outside_window")
        presented = request.headers.get(SIGNATURE_HEADER)
        if not presented:
            raise ProviderCallbackAuthenticationFailed("signature_missing")
        expected = callback_signature(
            derive_callback_key(
                self._master_secret,
                organization_id=organization_id,
                provider_key=provider_key,
                connection_key=connection_key,
            ),
            timestamp=timestamp,
            body=await request.body(),
        )
        if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
            raise ProviderCallbackAuthenticationFailed("signature_mismatch")
        return TrustedProviderCallbackContext(
            organization_id=organization_id,
            provider_key=provider_key,
            connection_key=connection_key,
        )


def _organization(raw: str | None) -> UUID:
    try:
        return UUID(raw or "")
    except ValueError:
        raise ProviderCallbackAuthenticationFailed("organization_missing_or_invalid") from None


def _timestamp(raw: str | None) -> int:
    if raw is None or not raw.isascii() or not raw.isdigit() or len(raw) > 12:
        raise ProviderCallbackAuthenticationFailed("timestamp_missing_or_invalid")
    return int(raw)
