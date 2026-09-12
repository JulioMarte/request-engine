from uuid import uuid4

import pytest
from pydantic import ValidationError

from request_engine.bootstrap.platform_server import create_app
from request_engine.bootstrap.settings import PlatformControlSettings


def test_private_server_requires_all_three_explicit_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL",
        "REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL",
        "REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        PlatformControlSettings.model_validate(
            {"database_url": "postgresql+asyncpg://app:test@localhost/product"},
        )


@pytest.mark.parametrize(
    "read_url",
    [
        "postgresql+asyncpg://app:test@localhost/product",
        "postgresql+asyncpg://reader:test@localhost/another_database",
        "postgresql+asyncpg://reader:test@another_host/product",
    ],
)
def test_private_server_rejects_mixed_endpoints_or_reused_logins(
    monkeypatch: pytest.MonkeyPatch, read_url: str
) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_DATABASE_URL", "postgresql+asyncpg://app:test@localhost/product"
    )
    monkeypatch.setenv("REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL", read_url)
    monkeypatch.setenv(
        "REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL",
        "postgresql+asyncpg://writer:test@localhost/product",
    )
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(uuid4()))
    with pytest.raises(ValueError, match="three distinct logins on the same database endpoint"):
        create_app()


@pytest.mark.parametrize(
    "query", ["host=other", "dbname=other", "service=other", "options=-crole=x"]
)
def test_private_settings_reject_hidden_connection_routing(query: str) -> None:
    with pytest.raises(ValidationError, match="cannot override endpoint or session identity"):
        PlatformControlSettings.model_validate(
            {
                "database_url": "postgresql+asyncpg://app:test@localhost/product",
                "platform_read_database_url": f"postgresql+asyncpg://reader:test@localhost/product?{query}",
                "platform_control_database_url": "postgresql+asyncpg://writer:test@localhost/product",
                "native_identity_authority_id": uuid4(),
            }
        )


@pytest.mark.parametrize(
    "url",
    ["postgresql+asyncpg://reader:test@localhost", "postgresql+psycopg://reader:test@/product"],
)
def test_private_settings_do_not_infer_database_or_host_from_driver_defaults(url: str) -> None:
    with pytest.raises(ValidationError, match="explicit host and database"):
        PlatformControlSettings.model_validate(
            {
                "database_url": "postgresql+asyncpg://app:test@localhost/product",
                "platform_read_database_url": url,
                "platform_control_database_url": "postgresql+asyncpg://writer:test@localhost/product",
                "native_identity_authority_id": uuid4(),
            }
        )
