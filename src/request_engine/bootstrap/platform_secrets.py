"""Composition for the governed platform secret-store boundary."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from request_engine.platform.secrets.openbao_secret_store import (
    OpenBaoPlatformSecretStore,
)
from request_engine.platform.secrets.platform_store import PlatformSecretStore


class PlatformSecretStoreSettings(BaseSettings):
    """Optional control-plane OpenBao configuration.

    Absence keeps configuration metadata usable while secret mutations fail
    closed with a typed service-unavailable response.
    """

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_", extra="ignore", hide_input_in_errors=True
    )

    openbao_addr: str | None = None
    openbao_token: SecretStr | None = None
    openbao_namespace: str | None = None
    openbao_mount: str = "secret"
    platform_secret_path_prefix: str = "request-engine/platform"
    openbao_timeout_seconds: float = Field(default=5.0, gt=0, le=30)


def build_platform_secret_store(
    settings: PlatformSecretStoreSettings | None = None,
) -> PlatformSecretStore | None:
    resolved = settings or PlatformSecretStoreSettings()
    address = resolved.openbao_addr
    if address is None or not address.strip():
        if resolved.openbao_token is not None:
            raise RuntimeError("REQUEST_ENGINE_OPENBAO_TOKEN requires REQUEST_ENGINE_OPENBAO_ADDR")
        return None
    return OpenBaoPlatformSecretStore(
        address=address,
        token=(
            None if resolved.openbao_token is None else resolved.openbao_token.get_secret_value()
        ),
        mount=resolved.openbao_mount,
        path_prefix=resolved.platform_secret_path_prefix,
        namespace=resolved.openbao_namespace,
        timeout_seconds=resolved.openbao_timeout_seconds,
    )
