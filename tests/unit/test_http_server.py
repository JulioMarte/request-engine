"""Deployment configuration must fail closed before accepting HTTP traffic."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from request_engine.bootstrap.server import create_app
from request_engine.bootstrap.settings import HttpSettings

pytestmark = pytest.mark.unit


@pytest.fixture
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_DATABASE_URL",
        "postgresql+asyncpg://request_app:test-only@127.0.0.1:1/unavailable",
    )
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(uuid4()))
    monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "a" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "b" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_OIDC_ENABLED", "false")


@pytest.mark.usefixtures("configured_environment")
@pytest.mark.asyncio
async def test_unavailable_database_prevents_startup_and_reports_unready() -> None:
    app = create_app()
    # Probe semantics independently of startup; ASGITransport does not start lifespan.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health/live")).json() == {"status": "alive"}
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert (await client.get("/openapi.json")).status_code == 200
    with pytest.raises(OSError):
        async with app.router.lifespan_context(app):
            pytest.fail("startup must not accept an unverified database login")


@pytest.mark.usefixtures("configured_environment")
def test_privileged_database_login_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_DATABASE_URL", "postgresql+asyncpg://postgres:secret@localhost/db"
    )
    with pytest.raises(ValidationError, match="least-privilege"):
        create_app()


@pytest.mark.usefixtures("configured_environment")
def test_missing_or_short_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY")
    with pytest.raises(ValidationError):
        create_app()
    monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "short")
    with pytest.raises(ValidationError, match="32 bytes"):
        create_app()


@pytest.mark.usefixtures("configured_environment")
def test_settings_hide_secrets_and_default_to_native_only() -> None:
    settings = HttpSettings.model_validate({})
    assert settings.oidc_enabled is False
    assert "test-only" not in repr(settings)
    assert "a" * 64 not in repr(settings)
