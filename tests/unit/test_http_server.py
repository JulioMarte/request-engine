from __future__ import annotations

import pytest
from pydantic import ValidationError

from request_engine.bootstrap.server import create_app
from request_engine.bootstrap.settings import HttpSettings


@pytest.fixture
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_DATABASE_URL",
        "postgresql+asyncpg://request_engine_app:test-only@localhost/request_engine",
    )
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "a" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RP_NAME", "Request Engine")
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS", "https://localhost")
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_DECOY_KEY", "b" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "c" * 64)


def test_missing_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUEST_ENGINE_DATABASE_URL")
    with pytest.raises(ValidationError):
        create_app()


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
def test_settings_hide_secrets() -> None:
    settings = HttpSettings.model_validate({})
    assert "test-only" not in repr(settings)
    assert "a" * 64 not in repr(settings)


@pytest.mark.usefixtures("configured_environment")
def test_managed_signing_allows_legacy_appointment_key_to_be_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY")
    monkeypatch.setenv(
        "REQUEST_ENGINE_APPOINTMENT_SIGNING_OPENBAO_ADDR",
        "http://127.0.0.1:18100",
    )
    monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_SIGNING_OPENBAO_TOKEN", "test-token")
    app = create_app()
    assert app is not None
