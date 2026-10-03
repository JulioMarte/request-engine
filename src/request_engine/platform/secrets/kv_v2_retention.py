"""Verified KV-v2 soft-deletion deadlines for short-lived bearer proofs."""

import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import httpx

from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)

_LOGGER = logging.getLogger("request_engine.secrets.retention")


async def configure_version_retention(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    headers: Mapping[str, str],
    expires_at: datetime,
    timeout_seconds: float,
) -> None:
    if expires_at.tzinfo is None:
        raise RecoveryDeliveryPermanent("secret retention requires an aware expiry")
    # Leave one request timeout plus rounding headroom between provider deletion
    # and business expiry. The actual version deadline is independently checked.
    seconds = (
        math.floor((expires_at - datetime.now(UTC)).total_seconds())
        - math.ceil(timeout_seconds)
        - 1
    )
    if seconds < 1:
        raise RecoveryDeliveryPermanent("secret retention lifetime is too short")
    try:
        response = await client.post(
            endpoint, headers=headers, json={"delete_version_after": f"{seconds}s"}
        )
    except httpx.TransportError:
        _LOGGER.warning("secret_retention_metadata_transport_failed")
        raise RecoveryDeliveryRetryable("secret retention metadata transport failed") from None
    if not response.is_success:
        _LOGGER.warning(
            "secret_retention_metadata_rejected", extra={"provider_status": response.status_code}
        )
        if response.status_code >= 500 or response.status_code == 429:
            raise RecoveryDeliveryRetryable("secret retention metadata unavailable")
        raise RecoveryDeliveryPermanent("secret retention metadata rejected")


def verify_version_retention(metadata: object, *, expires_at: datetime) -> None:
    """No successful staging receipt without a verified effective version TTL."""
    values: Mapping[str, object] = (
        cast("Mapping[str, object]", metadata) if isinstance(metadata, dict) else {}
    )
    deletion_time = values.get("deletion_time")
    try:
        if not isinstance(deletion_time, str) or not deletion_time:
            raise ValueError
        deletion_at = datetime.fromisoformat(deletion_time.replace("Z", "+00:00"))
        if deletion_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError
        if not datetime.now(UTC) < deletion_at <= expires_at:
            raise ValueError
        if values.get("destroyed") is True:
            raise ValueError
    except ValueError:
        _LOGGER.warning("secret_retention_deadline_unverified")
        # Never delete or rewrite this candidate: another transaction may have
        # retained it. Report the unsafe provider state without disclosing data.
        raise RecoveryDeliveryPermanent("secret retention deadline unverified") from None
