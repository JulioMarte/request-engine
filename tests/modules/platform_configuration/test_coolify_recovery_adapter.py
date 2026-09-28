from __future__ import annotations

import json

import httpx
import pytest

from request_engine.modules.platform_configuration.adapters.coolify_recovery import (
    CoolifyRecoveryAdapter,
)
from request_engine.modules.platform_configuration.application.deployment_reconciliation import (
    DeploymentBackupState,
    DeploymentBackupTarget,
)


def _row(*, frequency: str = "hourly") -> dict[str, object]:
    return {
        "uuid": "backup-1",
        "frequency": frequency,
        "save_s3": True,
        "database_backup_retention_days_locally": 7,
        "database_backup_retention_days_s3": 30,
        "timeout": 3600,
    }


@pytest.mark.asyncio
async def test_inspect_maps_coolify_schedule_without_leaking_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"backups": [_row()]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CoolifyRecoveryAdapter(
            base_url="https://coolify.example/api/v1/",
            api_token="super-secret",
            client=client,
        )
        state = await adapter.inspect_backup(DeploymentBackupTarget("db-1", "backup-1", "s3-1"))

    assert state == DeploymentBackupState("backup-1", "hourly", 7, 30, 3600, True)
    expected_url = httpx.URL("https://coolify.example/api/v1/databases/db-1/backups")
    assert seen[0].url == expected_url
    assert seen[0].headers["authorization"] == "Bearer super-secret"
    assert "super-secret" not in str(state)


@pytest.mark.asyncio
async def test_create_sends_supported_coolify_fields_and_re_reads_state() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"uuid": "backup-1"})
        return httpx.Response(200, json={"backups": [_row()]})

    desired = DeploymentBackupState(None, "hourly", 7, 30, 3600, True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CoolifyRecoveryAdapter(
            base_url="https://coolify.example/api/v1",
            api_token="token",
            client=client,
        )
        state = await adapter.create_backup(
            DeploymentBackupTarget("db-1", offsite_storage_id="s3-1"), desired
        )

    payload = json.loads(requests[0].content)
    assert payload == {
        "frequency": "hourly",
        "enabled": True,
        "save_s3": True,
        "s3_storage_uuid": "s3-1",
        "database_backup_retention_days_locally": 7,
        "database_backup_retention_days_s3": 30,
        "timeout": 3600,
    }
    assert state.schedule_id == "backup-1"
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_update_patches_exact_schedule_then_verifies_convergence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(200)
        return httpx.Response(200, json=[_row()])

    desired = DeploymentBackupState("backup-1", "hourly", 7, 30, 3600, True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CoolifyRecoveryAdapter(
            base_url="https://coolify.example/api/v1",
            api_token="token",
            client=client,
        )
        state = await adapter.update_backup(
            DeploymentBackupTarget("db-1", "backup-1", "s3-1"), desired
        )

    assert requests[0].method == "PATCH"
    assert requests[0].url.path == "/api/v1/databases/db-1/backups/backup-1"
    assert state.frequency == "hourly"


@pytest.mark.asyncio
async def test_multiple_schedules_fail_closed_without_explicit_schedule_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        second = dict(_row())
        second["uuid"] = "backup-2"
        return httpx.Response(200, json=[_row(), second])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CoolifyRecoveryAdapter(
            base_url="https://coolify.example/api/v1",
            api_token="token",
            client=client,
        )
        with pytest.raises(RuntimeError, match="explicit schedule_id"):
            await adapter.inspect_backup(DeploymentBackupTarget("db-1"))


@pytest.mark.asyncio
async def test_offsite_policy_requires_storage_id_before_side_effect() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    desired = DeploymentBackupState(None, "hourly", 7, 30, 3600, True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CoolifyRecoveryAdapter(
            base_url="https://coolify.example/api/v1",
            api_token="token",
            client=client,
        )
        with pytest.raises(ValueError, match="offsite_storage_id"):
            await adapter.create_backup(DeploymentBackupTarget("db-1"), desired)

    assert called is False


def test_coolify_adapter_refuses_plain_http_for_api_token() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        CoolifyRecoveryAdapter(base_url="http://coolify.example/api/v1", api_token="token")


def test_coolify_adapter_refuses_empty_token() -> None:
    with pytest.raises(ValueError, match="api_token"):
        CoolifyRecoveryAdapter(base_url="https://coolify.example/api/v1", api_token="")
