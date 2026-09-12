"""Runtime settings for Request Engine process composition.

Business/domain code must not import runtime settings directly. Entrypoints and the
composition root translate configuration into explicit dependencies.
"""

from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class HttpSettings(BaseSettings):
    """Explicit deployment configuration; no privileged or development defaults."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    native_identity_authority_id: UUID
    appointment_option_signing_key: SecretStr
    identity_exchange_fingerprint_key: SecretStr
    oidc_enabled: bool = False
    database_probe_timeout_seconds: float = Field(default=5, gt=0, le=30)

    @field_validator("database_url")
    @classmethod
    def validate_runtime_database(cls, value: SecretStr) -> SecretStr:
        url = make_url(value.get_secret_value())
        if url.drivername not in {"postgresql+asyncpg", "postgresql+psycopg"}:
            raise ValueError("an asynchronous PostgreSQL URL is required")
        if not url.username or url.username in {"postgres", "request_engine"}:
            raise ValueError("HTTP requires a dedicated least-privilege runtime login")
        return value

    @field_validator("appointment_option_signing_key", "identity_exchange_fingerprint_key")
    @classmethod
    def validate_signing_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("signing keys must contain at least 32 bytes")
        return value


class PlatformControlSettings(BaseSettings):
    """Explicit private-plane deployment; never inherits public-server defaults."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_", extra="ignore", hide_input_in_errors=True
    )
    database_url: SecretStr
    platform_read_database_url: SecretStr
    platform_control_database_url: SecretStr
    native_identity_authority_id: UUID
    database_probe_timeout_seconds: float = Field(default=5, gt=0, le=30)

    @field_validator("database_url", "platform_read_database_url", "platform_control_database_url")
    @classmethod
    def validate_database(cls, value: SecretStr) -> SecretStr:
        url = make_url(value.get_secret_value())
        if not url.host or not url.database:
            raise ValueError("private database URLs require an explicit host and database")
        routing_overrides = {
            "host",
            "port",
            "dbname",
            "database",
            "user",
            "username",
            "service",
            "servicefile",
            "options",
            "server_settings",
        }
        if routing_overrides.intersection(url.query):
            raise ValueError("private database URLs cannot override endpoint or session identity")
        return HttpSettings.validate_runtime_database(value)
