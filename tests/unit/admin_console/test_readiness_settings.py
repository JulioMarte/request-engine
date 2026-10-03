from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings


def _settings(directory: Path, **changes: Any) -> AdminConsoleSettings:
    values: dict[str, Any] = {
        "control_api_base_url": "http://control",
        "session_secret": SecretStr("readiness-test-secret-at-least-32-bytes"),
        "session_store_directory": directory,
        "cookie_secure": False,
    }
    return AdminConsoleSettings(**(values | changes))


class HealthApi:
    def __init__(self, result: int | None = 200) -> None:
        self.result = result
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if self.result is None:
            raise httpx.ConnectError("upstream-private-detail")
        return ControlResponse(self.result, {"detail": "upstream-private-detail"}, {})

    async def openapi(self) -> dict[str, Any]:
        return {}

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", ["control", "runtime"])
@pytest.mark.parametrize("result", [503, 401, None])
async def test_console_readiness_rejects_unready_dependency_without_leaking_payload(
    tmp_path: Path, dependency: str, result: int | None
) -> None:
    control = HealthApi(result if dependency == "control" else 200)
    runtime = HealthApi(result if dependency == "runtime" else 200)
    app = create_admin_console_app(
        _settings(tmp_path, runtime_api_base_url="http://runtime"),
        client=control,
        runtime_client=runtime,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert control.calls == runtime.calls == []
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unready",
        "reason": f"{dependency}_{'unreachable' if result is None else 'unready'}",
    }
    assert "upstream-private-detail" not in response.text
    for api in (control, runtime):
        assert all(method == "GET" and path == "/health/ready" for method, path, _ in api.calls)
        assert all(not kwargs for _, _, kwargs in api.calls)
    assert bool(runtime.calls) is (dependency == "runtime")


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_enabled", [False, True])
async def test_console_readiness_checks_only_enabled_apis(
    tmp_path: Path, tenant_enabled: bool
) -> None:
    control, runtime = HealthApi(), HealthApi()
    app = create_admin_console_app(
        _settings(tmp_path, runtime_api_base_url="http://runtime" if tenant_enabled else None),
        client=control,
        runtime_client=runtime if tenant_enabled else None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert control.calls == [("GET", "/health/ready", {})]
    assert runtime.calls == ([("GET", "/health/ready", {})] if tenant_enabled else [])


@pytest.mark.parametrize("field", ["control_api_base_url", "runtime_api_base_url"])
@pytest.mark.parametrize(
    "value",
    [
        "http://",
        "file:///etc/passwd",
        "https://user:private-secret@example.test",
        "https://example.test?token=private-secret",
        "https://example.test#private-secret",
        "http://example.test:invalid",
        "http://example.test:0",
        "http://exa mple.test",
        "http://example.test\n/path",
    ],
)
def test_api_configuration_rejects_invalid_or_secret_bearing_urls(
    tmp_path: Path, field: str, value: str
) -> None:
    with pytest.raises(ValidationError) as invalid:
        _settings(tmp_path, **{field: value})
    assert "private-secret" not in str(invalid.value)


def test_local_http_and_private_prefix_are_supported_without_credentials(tmp_path: Path) -> None:
    settings = _settings(tmp_path, control_api_base_url=" http://localhost:8011/private/ ")
    assert settings.control_api_base_url == "http://localhost:8011/private"
    assert settings.cookie_samesite == "lax"
    with pytest.raises(ValidationError, match="SameSite=None requires secure cookies"):
        _settings(tmp_path, cookie_samesite="none")
    assert _settings(tmp_path, cookie_samesite="none", cookie_secure=True).cookie_secure
