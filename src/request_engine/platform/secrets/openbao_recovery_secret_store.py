"""OpenBao KV v2 store for governed identity-recovery proofs.

Recovery proofs are short-lived bearer secrets, not platform configuration.
They use the existing RecoverySecretStore boundary and remain separate from the
general PlatformSecretStore. OpenBao is the self-hosted reference backend; a
local OpenBao Agent may inject authentication when token is omitted.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import httpx

from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
    StagedRecoverySecret,
)


class OpenBaoRecoverySecretStore:
    def __init__(
        self,
        *,
        address: str,
        token: str | None = None,
        mount: str = "secret",
        path_prefix: str = "request-engine/identity-recovery",
        timeout_seconds: float = 5.0,
        namespace: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not address.startswith(("http://", "https://")):
            raise ValueError("OpenBao address must be an http(s) URL")
        if token is not None and not token.strip():
            raise ValueError("OpenBao token cannot be blank")
        if not mount.strip() or not path_prefix.strip():
            raise ValueError("OpenBao mount and path prefix are required")
        self._address = address.rstrip("/")
        self._token = token
        self._mount = mount.strip("/")
        self._path_prefix = path_prefix.strip("/")
        self._timeout_seconds = timeout_seconds
        self._namespace = namespace
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._token is not None:
            headers["X-Vault-Token"] = self._token
        if self._namespace is not None:
            headers["X-Vault-Namespace"] = self._namespace
        return headers

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._address,
            timeout=self._timeout_seconds,
            transport=self._transport,
            trust_env=False,
        )

    def _path(self, case_id: UUID, generation: int) -> str:
        return f"{self._path_prefix}/{case_id}/{generation}"

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        path = self._path(case_id, generation)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        try:
            async with self._client() as client:
                response = await client.post(
                    f"/v1/{self._mount}/data/{path}",
                    headers=self._headers(),
                    json={
                        "data": {
                            "secret": secret,
                            "digest": digest,
                            "expires_at": expires_at.isoformat(),
                        },
                        "options": {"cas": 0},
                    },
                )
                if response.is_success:
                    await self._set_delete_version_after(client, path, expires_at)
                    return StagedRecoverySecret(
                        reference=path,
                        digest=digest,
                        expires_at=expires_at,
                        created=True,
                    )
                if response.status_code == 400 and _mentions_cas(response.text):
                    return await self._read_staged(client, path)
                if response.status_code >= 500:
                    raise RecoveryDeliveryRetryable("OpenBao secret store is unavailable")
                raise RecoveryDeliveryPermanent("OpenBao rejected recovery secret staging")
        except httpx.TransportError as exc:
            raise RecoveryDeliveryRetryable("OpenBao secret staging transport failure") from exc

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        path = self._path(case_id, generation)
        try:
            async with self._client() as client:
                response = await client.delete(
                    f"/v1/{self._mount}/metadata/{path}",
                    headers=self._headers(),
                )
        except httpx.TransportError as exc:
            raise RecoveryDeliveryRetryable("OpenBao secret discard transport failure") from exc
        if response.status_code == 404 or response.is_success:
            return
        if response.status_code >= 500:
            raise RecoveryDeliveryRetryable("OpenBao secret store is unavailable")
        raise RecoveryDeliveryPermanent("OpenBao rejected recovery secret discard")

    async def read(self, *, reference: str) -> str:
        if not reference.startswith(f"{self._path_prefix}/"):
            raise RecoveryDeliveryPermanent("recovery secret reference is outside OpenBao scope")
        try:
            async with self._client() as client:
                response = await client.get(
                    f"/v1/{self._mount}/data/{reference}",
                    headers=self._headers(),
                )
        except httpx.TransportError as exc:
            raise RecoveryDeliveryRetryable("OpenBao secret read transport failure") from exc
        if response.status_code == 404:
            raise RecoveryDeliveryPermanent("staged recovery secret is unavailable")
        if not response.is_success:
            if response.status_code >= 500:
                raise RecoveryDeliveryRetryable("OpenBao secret store is unavailable")
            raise RecoveryDeliveryPermanent("OpenBao rejected recovery secret read")
        payload = _parse_payload(response)
        secret = payload.get("secret")
        if not isinstance(secret, str):
            raise RecoveryDeliveryPermanent("OpenBao returned a malformed staged secret")
        expires_at_raw = payload.get("expires_at")
        if expires_at_raw is not None:
            expires_at = _parse_expires_at(expires_at_raw)
            if expires_at <= datetime.now(UTC):
                raise RecoveryDeliveryPermanent("staged recovery secret has expired")
        return secret

    async def _read_staged(
        self,
        client: httpx.AsyncClient,
        path: str,
    ) -> StagedRecoverySecret:
        response = await client.get(
            f"/v1/{self._mount}/data/{path}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            raise RecoveryDeliveryRetryable(
                "staged recovery secret vanished during create-if-absent"
            )
        if not response.is_success:
            if response.status_code >= 500:
                raise RecoveryDeliveryRetryable("OpenBao secret store is unavailable")
            raise RecoveryDeliveryPermanent("OpenBao rejected staged recovery secret read")
        payload = _parse_payload(response)
        secret = payload.get("secret")
        digest = payload.get("digest")
        expires_at_raw = payload.get("expires_at")
        if not isinstance(secret, str) or not isinstance(digest, str) or expires_at_raw is None:
            raise RecoveryDeliveryPermanent("OpenBao returned malformed staged secret")
        expires_at = _parse_expires_at(expires_at_raw)
        try:
            return StagedRecoverySecret(
                reference=path,
                digest=digest,
                expires_at=expires_at,
                created=False,
            )
        except ValueError as exc:
            raise RecoveryDeliveryPermanent("OpenBao returned malformed staged secret") from exc

    async def _set_delete_version_after(
        self,
        client: httpx.AsyncClient,
        path: str,
        expires_at: datetime,
    ) -> None:
        with contextlib.suppress(Exception):
            seconds = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
            await client.post(
                f"/v1/{self._mount}/metadata/{path}",
                headers=self._headers(),
                json={"delete_version_after": f"{seconds}s"},
            )


def _mentions_cas(body: str) -> bool:
    lowered = body.lower()
    return "check-and-set" in lowered or "cas" in lowered


def _parse_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        raw_body: object = response.json()
    except ValueError as exc:
        raise RecoveryDeliveryPermanent("OpenBao returned malformed response") from exc
    if not isinstance(raw_body, dict):
        raise RecoveryDeliveryPermanent("OpenBao returned malformed response")
    body = cast(dict[str, object], raw_body)
    raw_data = body.get("data")
    if not isinstance(raw_data, dict):
        raise RecoveryDeliveryPermanent("OpenBao returned malformed response")
    data = cast(dict[str, object], raw_data)
    payload = data.get("data")
    if not isinstance(payload, dict):
        raise RecoveryDeliveryPermanent("OpenBao returned malformed response")
    return cast(dict[str, Any], payload)


def _parse_expires_at(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise RecoveryDeliveryPermanent("OpenBao returned malformed staged secret")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryDeliveryPermanent("OpenBao returned malformed staged secret") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value
