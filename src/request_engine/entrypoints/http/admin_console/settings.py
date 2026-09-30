"""Runtime settings for the private admin console entrypoint.

The current signed-cookie transport provides integrity but is not a server-side
session store. Credential material must not be described as server-only until
the opaque-handle session-store boundary is installed.
"""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ALLOWED_SAMESITE = frozenset({"lax", "strict", "none"})


class AdminConsoleSettings(BaseSettings):
    """Explicit private-console configuration; no privileged defaults."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_ADMIN_CONSOLE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    control_api_base_url: str
    runtime_api_base_url: str | None = None
    session_secret: SecretStr
    session_cookie_name: str = "re_admin_console"
    setup_cookie_name: str = "re_admin_setup"
    session_ttl_seconds: int = Field(default=1800, ge=60, le=43200)
    setup_ttl_seconds: int = Field(default=1800, ge=60, le=3600)
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    request_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    openapi_cache_seconds: int = Field(default=60, ge=0, le=3600)
    log_level: str = "INFO"
    debug: bool = False

    @field_validator("control_api_base_url", "runtime_api_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip().rstrip("/")
        if not trimmed.startswith(("http://", "https://")):
            raise ValueError("control_api_base_url must be an absolute http(s) URL")
        return trimmed

    @field_validator("session_cookie_name", "setup_cookie_name")
    @classmethod
    def validate_cookie_name(cls, value: str) -> str:
        if not value.strip() or any(character in value for character in " ;,"):
            raise ValueError("cookie names must be non-empty and free of separators")
        return value

    @field_validator("cookie_samesite")
    @classmethod
    def validate_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SAMESITE:
            raise ValueError(f"cookie_samesite must be one of {sorted(_ALLOWED_SAMESITE)}")
        return normalized

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode()) < 32:
            raise ValueError("session_secret must contain at least 32 bytes")
        return value


__all__ = ["AdminConsoleSettings"]
