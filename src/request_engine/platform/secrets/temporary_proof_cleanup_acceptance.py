"""Explicit-version cleanup from trusted expiry receipts, never namespace discovery."""

import hashlib
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
    path = quote(receipt.reference, safe="/")
    metadata_endpoint = f"/v1/{mount}/metadata/{path}"

    async def inspect() -> str:
        try:
            response = await client.get(metadata_endpoint, headers=headers)
        except httpx.TransportError:
            return "unresolved"
        if response.status_code == 404:
            return "absent"
        if response.status_code in (401, 403):
            raise RecoveryDeliveryPermanent("temporary proof cleanup access rejected")
        if not response.is_success:
            return "unresolved"
        try:
            version = response.json()["data"]["versions"][str(receipt.version)]
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
        except (ValueError, TypeError, KeyError, AttributeError):
            return "unverified"
        return "eligible"

    initial = await inspect()
    if initial != "eligible":
        return result(initial)
    try:
        response = await client.post(
            f"/v1/{mount}/destroy/{path}", headers=headers, json={"versions": [receipt.version]}
        )
        if response.status_code in (401, 403):
            raise RecoveryDeliveryPermanent("temporary proof cleanup access rejected")
    except httpx.TransportError:
        pass
    # Even a successful response is not proof until the exact version is inspected.
    final = await inspect()
    return result("unresolved" if final == "eligible" else final)
