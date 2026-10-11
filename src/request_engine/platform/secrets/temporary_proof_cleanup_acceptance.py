"""Explicit-version cleanup from trusted expiry receipts, never namespace discovery."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

from request_engine.platform.secrets.delivery import RecoveryDeliveryPermanent


@dataclass(frozen=True)
class TemporaryProofExpiryReceipt:
    reference: str
    version: int
    expires_at: datetime
    created_at: datetime
    deletion_at: datetime

    def __post_init__(self) -> None:
        parts = self.reference.split("/")
        if parts[:2] == ["request-engine", "identity-recovery"] and len(parts) == 4:
            UUID(parts[2])
        elif parts[:2] == ["request-engine", "temporary-proof-retention-probe"] and len(parts) == 5:
            UUID(parts[2])
            UUID(parts[3])
        else:
            raise ValueError("unsupported temporary proof namespace")
        if not parts[-1].isdigit() or int(parts[-1]) < 1 or self.version < 1:
            raise ValueError("invalid temporary proof version")
        if any(
            value.tzinfo is None for value in (self.expires_at, self.created_at, self.deletion_at)
        ):
            raise ValueError("aware retention timestamps required")
        if not self.created_at < self.deletion_at <= self.expires_at:
            raise ValueError("invalid retention receipt deadlines")

    @property
    def cleanup_key(self) -> str:
        identity = f"{self.reference}:{self.version}:{self.created_at.isoformat()}"
        return hashlib.sha256(identity.encode()).hexdigest()


@dataclass(frozen=True)
class TemporaryProofCleanupResult:
    cleanup_key: str
    outcome: str


async def inspect_expired_temporary_version(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    receipt: TemporaryProofExpiryReceipt,
    now: datetime,
    grace: timedelta,
    mount: str,
) -> str:
    """Metadata-only reconciliation, with a total five-second/64KiB response budget."""
    path = quote(receipt.reference, safe="/")
    try:
        async with (
            asyncio.timeout(5),
            client.stream(
                "GET",
                f"/v1/{mount}/metadata/{path}",
                headers={**headers, "Accept-Encoding": "identity"},
            ) as response,
        ):
            if response.status_code == 404:
                return "absent"
            if response.status_code in (401, 403):
                return "denied"
            if not response.is_success:
                return "unresolved"
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                return "unverified"  # Do not decompress a provider-controlled expansion.
            body = bytearray()
            if response.is_stream_consumed:
                # In-memory transport doubles can supply a pre-consumed response.
                if len(response.content) > 65536:
                    return "unverified"
                body.extend(response.content)
            else:
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > 65536:
                        return "unverified"
                    body.extend(chunk)
    except (httpx.TransportError, TimeoutError):
        return "unresolved"
    try:
        version = json.loads(body)["data"]["versions"][str(receipt.version)]
        created = datetime.fromisoformat(version["created_time"].replace("Z", "+00:00"))
        if created != receipt.created_at:
            return "unverified"
        if version.get("destroyed") is True:
            return "destroyed"
        deletion = datetime.fromisoformat(version["deletion_time"].replace("Z", "+00:00"))
        if deletion != receipt.deletion_at:
            return "unverified"
        if version.get("destroyed") is not False or deletion + grace > now:
            return "unverified"
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return "unverified"
    return "eligible"


async def submit_temporary_version_destruction(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    receipt: TemporaryProofExpiryReceipt,
    mount: str,
) -> str:
    """Ignore response bodies; a bounded submission is never completion evidence."""
    path = quote(receipt.reference, safe="/")
    try:
        async with (
            asyncio.timeout(5),
            client.stream(
                "POST",
                f"/v1/{mount}/destroy/{path}",
                headers=headers,
                json={"versions": [receipt.version]},
            ) as response,
        ):
            return "denied" if response.status_code in (401, 403) else "submitted"
    except (httpx.TransportError, TimeoutError):
        return "unresolved"  # Ambiguous outcome must be reconciled, not blindly retried.


async def probe_expired_temporary_proof_destruction(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    receipt: TemporaryProofExpiryReceipt,
    now: datetime,
    grace: timedelta,
    mount: str = "secret",
    isolated_acceptance: bool = False,
) -> TemporaryProofCleanupResult:
    """Caller supplies trusted retained-version expiry, not a losing candidate's expiry.

    KV-v2 destroy has no CAS. Metadata DELETE/recreation can reuse version numbers;
    therefore this is ONLY an isolated acceptance primitive, not production cleanup.
    Loopback cannot prove isolation: the operator must exclude production tunnels.
    No automatic retry: a subsequent call inspects the same named version again.
    Neither provider response bodies nor credentials/references enter results/errors.
    """
    provider_url = urlsplit(str(client.base_url))
    if (
        not isolated_acceptance
        or client.follow_redirects
        or provider_url.scheme not in ("http", "https")
        or provider_url.hostname not in ("localhost", "127.0.0.1", "::1")
        or provider_url.username
        or provider_url.password
        or provider_url.path not in ("", "/")
        or provider_url.query
        or provider_url.fragment
    ):
        raise ValueError("temporary proof destruction requires isolated loopback acceptance")
    if now.tzinfo is None or grace < timedelta(seconds=1):
        raise ValueError("aware clock and positive cleanup grace required")
    mount_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not mount or any(char not in mount_chars for char in mount):
        raise ValueError("invalid KV mount")

    def result(outcome: str) -> TemporaryProofCleanupResult:
        return TemporaryProofCleanupResult(receipt.cleanup_key, outcome)

    if now < receipt.expires_at + grace:
        return result("retained")

    async def inspect() -> str:
        outcome = await inspect_expired_temporary_version(
            client, headers=headers, receipt=receipt, now=now, grace=grace, mount=mount
        )
        if outcome == "denied":
            raise RecoveryDeliveryPermanent("temporary proof cleanup access rejected")
        return outcome

    initial = await inspect()
    if initial != "eligible":
        return result(initial)
    submitted = await submit_temporary_version_destruction(
        client,
        headers=headers,
        receipt=receipt,
        mount=mount,
    )
    if submitted == "denied":
        raise RecoveryDeliveryPermanent("temporary proof cleanup access rejected")
    # Even a successful response is not proof until the exact version is inspected.
    final = await inspect()
    return result("unresolved" if final == "eligible" else final)
