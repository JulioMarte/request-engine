from __future__ import annotations

from typing import Any, cast

import httpx

from request_engine.modules.platform_configuration.application.deployment_reconciliation import (
    DeploymentBackupState,
    DeploymentBackupTarget,
)


class CoolifyRecoveryAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = httpx.URL(base_url.rstrip("/"))
        if url.scheme != "https" or not url.host or url.query or url.fragment:
            raise ValueError("Coolify base_url must be an HTTPS origin/path without query or fragment")
        if not api_token:
            raise ValueError("Coolify api_token must not be empty")
        self._base_url = str(url).rstrip("/")
        self._api_token = api_token
        self._client = client

    @property
    def provider_kind(self) -> str:
        return "coolify"

    async def inspect_backup(
        self,
        target: DeploymentBackupTarget,
    ) -> DeploymentBackupState | None:
        response = await self._request("GET", f"/databases/{target.resource_id}/backups")
        response.raise_for_status()
        rows = _backup_rows(response.json())
        if target.schedule_id is not None:
            row = next(
                (item for item in rows if str(item.get("uuid")) == target.schedule_id),
                None,
            )
        elif len(rows) == 1:
            row = rows[0]
        elif not rows:
            return None
        else:
            raise RuntimeError("multiple Coolify backup schedules require an explicit schedule_id")
        return None if row is None else _state(row)

    async def create_backup(
        self,
        target: DeploymentBackupTarget,
        desired: DeploymentBackupState,
    ) -> DeploymentBackupState:
        response = await self._request(
            "POST",
            f"/databases/{target.resource_id}/backups",
            json=_payload(target, desired),
        )
        response.raise_for_status()
        schedule_id = _optional_string(_mapping(response.json()).get("uuid"))
        if schedule_id is None:
            raise RuntimeError("Coolify create backup response did not return a schedule uuid")
        return await self._inspect_explicit(target, schedule_id)

    async def update_backup(
        self,
        target: DeploymentBackupTarget,
        desired: DeploymentBackupState,
    ) -> DeploymentBackupState:
        schedule_id = target.schedule_id or desired.schedule_id
        if schedule_id is None:
            raise RuntimeError("Coolify backup update requires a schedule_id")
        response = await self._request(
            "PATCH",
            f"/databases/{target.resource_id}/backups/{schedule_id}",
            json=_payload(target, desired),
        )
        response.raise_for_status()
        return await self._inspect_explicit(target, schedule_id)

    async def _inspect_explicit(
        self,
        target: DeploymentBackupTarget,
        schedule_id: str,
    ) -> DeploymentBackupState:
        state = await self.inspect_backup(
            DeploymentBackupTarget(
                resource_id=target.resource_id,
                schedule_id=schedule_id,
                offsite_storage_id=target.offsite_storage_id,
            )
        )
        if state is None:
            raise RuntimeError("Coolify backup schedule disappeared after mutation")
        return state

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_token}"}
        url = f"{self._base_url}{path}"
        if self._client is not None:
            return await self._client.request(method, url, headers=headers, **kwargs)
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            return await client.request(method, url, headers=headers, **kwargs)


def _payload(
    target: DeploymentBackupTarget,
    desired: DeploymentBackupState,
) -> dict[str, object]:
    if (
        desired.frequency is None
        or desired.local_retention_days is None
        or desired.timeout_seconds is None
    ):
        raise ValueError("desired backup state is incomplete")
    if desired.offsite_enabled and target.offsite_storage_id is None:
        raise ValueError("offsite_storage_id is required when offsite backup is enabled")
    payload: dict[str, object] = {
        "frequency": desired.frequency,
        "enabled": True,
        "save_s3": bool(desired.offsite_enabled),
        "database_backup_retention_days_locally": desired.local_retention_days,
        "timeout": desired.timeout_seconds,
    }
    if desired.offsite_enabled:
        if desired.offsite_retention_days is None:
            raise ValueError("offsite retention is required when offsite backup is enabled")
        payload["s3_storage_uuid"] = cast(str, target.offsite_storage_id)
        payload["database_backup_retention_days_s3"] = desired.offsite_retention_days
    return payload


def _backup_rows(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [_mapping(item) for item in cast(list[object], value)]
    mapping = _mapping(value)
    for key in ("backups", "data"):
        rows = mapping.get(key)
        if isinstance(rows, list):
            return [_mapping(item) for item in cast(list[object], rows)]
    return [mapping] if "uuid" in mapping else []


def _state(row: dict[str, object]) -> DeploymentBackupState:
    return DeploymentBackupState(
        schedule_id=_optional_string(row.get("uuid")),
        frequency=_optional_string(row.get("frequency")),
        local_retention_days=_optional_int(
            row.get("database_backup_retention_days_locally")
        ),
        offsite_retention_days=_optional_int(row.get("database_backup_retention_days_s3")),
        timeout_seconds=_optional_int(row.get("timeout")),
        offsite_enabled=_optional_bool(row.get("save_s3")),
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError("Coolify returned an unexpected response shape")
    return {str(key): item for key, item in cast(dict[object, object], value).items()}


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
