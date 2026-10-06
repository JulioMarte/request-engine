"""Compose invitation delivery using the governed secret store and SMTP policy."""

from urllib.parse import urlsplit

from request_engine.bootstrap.recovery_delivery import (
    RecoveryDeliverySettings,
    build_recovery_secret_delivery,
    build_recovery_secret_store,
    has_recovery_secret_store_configuration,
)
from request_engine.modules.platform_configuration.adapters.managed_smtp_delivery import (
    ManagedSmtpRecoveryDeliveryChannel,
)
from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfigurationResolver,
)
from request_engine.platform.secrets.delivery import RecoverySecretDelivery, RecoverySecretStaging
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel


def _acceptance_url(settings: RecoveryDeliverySettings) -> str | None:
    """Deployment-owned URL; HTTPS or loopback development, never caller redirect."""
    url = settings.staff_invitation_accept_url
    if url is None or not url.strip():
        return None
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/staff-invitations"
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise RuntimeError("staff invitation acceptance URL must be a trusted console HTTPS path")
    return url


def build_staff_invitation_staging(
    settings: RecoveryDeliverySettings,
) -> RecoverySecretStaging | None:
    """HTTP issues proof retention; only the worker resolves governed SMTP.

    The application role intentionally cannot read installation-wide provider
    configuration. Missing fallback SMTP must not disable issuance when the
    worker uses API-managed SMTP. Transport availability is delivery state,
    never a promise inferred from staging configuration.
    """
    if _acceptance_url(settings) is None:
        return None
    return build_recovery_secret_store(settings)


def build_staff_invitation_delivery(
    settings: RecoveryDeliverySettings,
    *,
    resolver: ActivePlatformConfigurationResolver | None = None,
) -> RecoverySecretDelivery | None:
    """Worker transport using managed SMTP or explicit bootstrap fallback."""
    url = _acceptance_url(settings)
    if url is None:
        return None
    if not has_recovery_secret_store_configuration(settings):
        return None
    fallback = None
    if settings.smtp_host and settings.smtp_sender:
        fallback = SmtpRecoveryDeliveryChannel(
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=settings.smtp_sender,
            username=settings.smtp_username,
            password=(
                None
                if settings.smtp_password is None
                else settings.smtp_password.get_secret_value()
            ),
            starttls=settings.smtp_starttls,
            use_ssl=settings.smtp_ssl,
            timeout_seconds=settings.smtp_timeout_seconds,
            reset_url=url,
            purpose="staff_invitation",
        )
    channel = (
        ManagedSmtpRecoveryDeliveryChannel(
            resolver=resolver, fallback=fallback, reset_url=url, purpose="staff_invitation"
        )
        if resolver is not None
        else fallback
    )
    if channel is None:
        return None
    return build_recovery_secret_delivery(
        settings.model_copy(update={"recovery_delivery_factory": None}),
        channel_override=channel,
    )
