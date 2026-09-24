"""Dedicated OpenBao boundary for appointment-option signing keyrings."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from request_engine.platform.secrets.openbao_secret_store import OpenBaoPlatformSecretStore
from request_engine.platform.secrets.platform_store import PlatformSecretStore


class AppointmentSigningSecretStoreSettings(BaseSettings):
    """Per-process signing-store configuration with a dedicated env prefix."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_APPOINTMENT_SIGNING_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    openbao_addr: str | None = None
    openbao_token: SecretStr | None = None
    openbao_namespace: str | None = None
    openbao_mount: str = "secret"
    secret_path_prefix: str = "request-engine/signing"
    openbao_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    poll_interval_seconds: float = Field(default=5.0, gt=0, le=300)


def build_appointment_signing_secret_store(
    settings: AppointmentSigningSecretStoreSettings | None = None,
) -> PlatformSecretStore | None:
    resolved = settings or AppointmentSigningSecretStoreSettings()
    address = resolved.openbao_addr
    token = (
        None
        if resolved.openbao_token is None
        else resolved.openbao_token.get_secret_value().strip() or None
    )
    if address is None or not address.strip():
        if token is not None:
            raise RuntimeError(
                "REQUEST_ENGINE_APPOINTMENT_SIGNING_OPENBAO_TOKEN requires "
                "REQUEST_ENGINE_APPOINTMENT_SIGNING_OPENBAO_ADDR"
            )
        return None
    return OpenBaoPlatformSecretStore(
        address=address,
        token=token,
        mount=resolved.openbao_mount,
        path_prefix=resolved.secret_path_prefix,
        namespace=resolved.openbao_namespace,
        timeout_seconds=resolved.openbao_timeout_seconds,
    )
