"""Compose owner account invitation email (ADR 0021): SMTP only, digest-only storage."""

from urllib.parse import urlsplit

from request_engine.bootstrap.recovery_delivery import RecoveryDeliverySettings
from request_engine.modules.platform_configuration.adapters.managed_smtp_delivery import (
    ManagedSmtpRecoveryDeliveryChannel,
)
from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfigurationResolver,
)
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel


def account_invitation_enrollment_url(settings: RecoveryDeliverySettings) -> str | None:
    """Deployment-owned app URL; HTTPS or loopback development, never caller supplied."""
    url = settings.account_invitation_accept_url
    if url is None or not url.strip():
        return None
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/account-invitations"
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    ):
        raise RuntimeError("account invitation URL must be a trusted HTTPS /account-invitations")
    return url


def build_account_invitation_mailer(
    settings: RecoveryDeliverySettings,
    *,
    resolver: ActivePlatformConfigurationResolver | None,
) -> ManagedSmtpRecoveryDeliveryChannel | SmtpRecoveryDeliveryChannel | None:
    """Managed ACTIVE SMTP with optional bootstrap fallback; ``None`` keeps email at 503."""
    url = account_invitation_enrollment_url(settings)
    if url is None:
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
            purpose="account_invitation",
        )
    if resolver is None:
        return fallback
    return ManagedSmtpRecoveryDeliveryChannel(
        resolver=resolver, fallback=fallback, reset_url=url, purpose="account_invitation"
    )
