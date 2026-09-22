"""OpenBao KV v2 implementation of the platform secret-store contract.

The adapter is API-compatible with the Vault-style KV v2 HTTP surface but is
named for the self-hosted reference backend selected by Request Engine. It can
authenticate directly with a short-lived token or talk to an OpenBao Agent
proxy that injects its auto-auth token.

Callers supply only an opaque UUID. Backend paths are derived internally under
one configured prefix.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

import httpx

from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict,
    PlatformSecretMetadata,
    PlatformSecretNotFound,
    PlatformSecretStoreUnavailable,
)


class OpenBaoPlatformSecretStore:
    def __init__(
        self,
        *,
        address: str,
        token: str | None = None,
        mount: str = "secret",
        path_prefix: str = "request-engine/platform",
        namespace: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not address.startswith(("http://", "https://")):
            raise ValueError("OpenBao address must be an http(s) URL")
        if token is not None and not token.strip():
            raise ValueError("OpenBao token cannot be blank")
        if not mount.strip() or not path_prefix.strip():
            raise ValueError("OpenBao mount and path prefix are required")
        if timeout_seconds <= 0:
            raise ValueError("OpenBao timeout must be positive")
        self._address = address.rstrip("/")
        self._token = token
        self._mount = mount.strip("/")
        self._path_prefix = path_prefix.strip("/")
        self._namespace = namespace
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def _path(self, secret_id: UUID) -> str:
        return f"{self._path_prefix}/{secret_id}"

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

    async def write(
        self,
        *,
        secret_id: UUID,
        value: str,
        expected_version: int | None,
        operation_id: UUID | None = None,
    ) -> PlatformSecretMetadata:
        if not value:
            raise ValueError("secret value cannot be empty")
        if expected_version is not None and expected_version <= 0:
            raise ValueError("expected secret version must be positive")
        cas = 0 if expected_version is None else expected_version
        try:
            async with self._client() as client:
                response = await client.post(
                    f"/v1/{self._mount}/data/{self._path(secret_id)}",
                    headers=self._headers(),
                    json={
                        "data": {
                            "value": value,
                            "operation_id": None if operation_id is None else str(operation_id),
                        },
                        "options": {"cas": cas},
                    },
                )
        except httpx.TransportError as exc:
            raise PlatformSecretStoreUnavailable("OpenBao secret write failed") from exc
        if response.status_code == 400 and _is_cas_conflict(response):
            raise PlatformSecretConflict("OpenBao secret version changed")
        if not response.is_success:
            raise _backend_error(response, "write")
        data = _response_data(response)
        version = data.get("version")
        if not isinstance(version, int) or version <= 0:
            # Some compatible proxies omit write metadata. Read it back rather
            # than guessing a version that would weaken future CAS rotations.
            return await self.metadata(secret_id=secret_id)
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=version,
            created_at=_optional_datetime(data.get("created_time")),
            operation_id=operation_id,
        )

    async def resolve(self, *, secret_id: UUID) -> str:
        try:
            async with self._client() as client:
                response = await client.get(
                    f"/v1/{self._mount}/data/{self._path(secret_id)}",
                    headers=self._headers(),
                )
        except httpx.TransportError as exc:
            raise PlatformSecretStoreUnavailable("OpenBao secret read failed") from exc
        if response.status_code == 404:
            raise PlatformSecretNotFound("OpenBao secret does not exist")
        if not response.is_success:
            raise _backend_error(response, "read")
        data = _response_data(response)
        secret_data = data.get("data")
        if not isinstance(secret_data, dict):
            raise PlatformSecretStoreUnavailable("OpenBao returned malformed secret data")
        value = cast(dict[str, Any], secret_data).get("value")
        if not isinstance(value, str):
            raise PlatformSecretStoreUnavailable("OpenBao returned malformed secret value")
        return value

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        """Read current version plus the opaque mutation marker, never plaintext.

        KV-v2's metadata endpoint does not return custom data fields, so
        reconciliation reads the data endpoint and intentionally discards the
        secret value. This lets a retry distinguish "our prior write succeeded
        but the response was lost" from a genuinely conflicting writer.
        """

        try:
            async with self._client() as client:
                response = await client.get(
                    f"/v1/{self._mount}/data/{self._path(secret_id)}",
                    headers=self._headers(),
                )
        except httpx.TransportError as exc:
            raise PlatformSecretStoreUnavailable("OpenBao metadata read failed") from exc
        if response.status_code == 404:
            raise PlatformSecretNotFound("OpenBao secret does not exist")
        if not response.is_success:
            raise _backend_error(response, "metadata read")
        data = _response_data(response)
        secret_data = data.get("data")
        metadata = data.get("metadata")
        if not isinstance(secret_data, dict) or not isinstance(metadata, dict):
            raise PlatformSecretStoreUnavailable("OpenBao returned malformed secret metadata")
        secret_fields = cast(dict[str, Any], secret_data)
        metadata_fields = cast(dict[str, Any], metadata)
        version = metadata_fields.get("version")
        if not isinstance(version, int) or version <= 0:
            raise PlatformSecretStoreUnavailable("OpenBao returned malformed secret metadata")
        raw_operation_id = secret_fields.get("operation_id")
        operation_id: UUID | None = None
        if raw_operation_id is not None:
            if not isinstance(raw_operation_id, str):
                raise PlatformSecretStoreUnavailable("OpenBao returned malformed operation marker")
            try:
                operation_id = UUID(raw_operation_id)
            except ValueError as exc:
                raise PlatformSecretStoreUnavailable(
                    "OpenBao returned malformed operation marker"
                ) from exc
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=version,
            created_at=_optional_datetime(metadata_fields.get("created_time")),
            updated_at=_optional_datetime(metadata_fields.get("updated_time")),
            operation_id=operation_id,
        )

    async def revoke(self, *, secret_id: UUID) -> None:
        try:
            async with self._client() as client:
                response = await client.delete(
                    f"/v1/{self._mount}/metadata/{self._path(secret_id)}",
                    headers=self._headers(),
                )
        except httpx.TransportError as exc:
            raise PlatformSecretStoreUnavailable("OpenBao secret revocation failed") from exc
        if response.status_code == 404:
            return
        if not response.is_success:
            raise _backend_error(response, "revoke")


def _response_data(response: httpx.Response) -> dict[str, Any]:
    try:
        raw_body: object = response.json()
    except ValueError as exc:
        raise PlatformSecretStoreUnavailable("OpenBao returned malformed JSON") from exc
    if not isinstance(raw_body, dict):
        raise PlatformSecretStoreUnavailable("OpenBao returned malformed response data")
    body = cast(dict[str, object], raw_body)
    raw_data = body.get("data")
    if not isinstance(raw_data, dict):
        raise PlatformSecretStoreUnavailable("OpenBao returned malformed response data")
    return cast(dict[str, Any], raw_data)


def _is_cas_conflict(response: httpx.Response) -> bool:
    text = response.text.lower()
    return "check-and-set" in text or "cas" in text


def _backend_error(response: httpx.Response, operation: str) -> PlatformSecretStoreUnavailable:
    return PlatformSecretStoreUnavailable(
        f"OpenBao rejected secret {operation} with status {response.status_code}"
    )


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
