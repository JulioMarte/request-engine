from __future__ import annotations

import asyncio
import hashlib
import smtplib
import ssl
from email.message import EmailMessage

from request_engine.modules.platform_configuration.application.smtp import (
    ProviderTestOutcome,
    ProviderTestResult,
    ProviderValidationResult,
    ProviderValidationStatus,
    SmtpConfiguration,
    SmtpConfigurationValidator,
    SmtpProviderTester,
    SmtpSecurityMode,
)


def _verified_tls_context() -> ssl.SSLContext:
    """TLS context that verifies the server certificate and hostname.

    ``smtplib`` defaults to ``ssl._create_stdlib_context()`` for both
    ``SMTP_SSL`` and ``starttls``, which performs **no** certificate or
    hostname verification. Callers must pass a verifying context explicitly so
    an on-path attacker cannot impersonate the SMTP provider.
    """

    return ssl.create_default_context()


def _connect(configuration: SmtpConfiguration) -> smtplib.SMTP:
    """Open a connection using certificate-verifying TLS for implicit-TLS mode."""

    if configuration.security is SmtpSecurityMode.TLS:
        return smtplib.SMTP_SSL(
            configuration.host,
            configuration.port,
            timeout=configuration.timeout_seconds,
            context=_verified_tls_context(),
        )
    return smtplib.SMTP(
        configuration.host,
        configuration.port,
        timeout=configuration.timeout_seconds,
    )


class SmtplibConfigurationValidator(SmtpConfigurationValidator):
    """Validate SMTP connectivity/TLS/auth without sending a message."""

    async def validate(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
    ) -> ProviderValidationResult:
        return await asyncio.to_thread(
            self._validate_blocking,
            configuration,
            password,
        )

    @staticmethod
    def _validate_blocking(
        configuration: SmtpConfiguration,
        password: str | None,
    ) -> ProviderValidationResult:
        try:
            with _connect(configuration) as client:
                code, _ = client.ehlo(configuration.helo_name or "")
                if code >= 400:
                    return ProviderValidationResult(
                        ProviderValidationStatus.INVALID,
                        "smtp_ehlo_rejected",
                    )
                if configuration.security is SmtpSecurityMode.STARTTLS:
                    client.starttls(context=_verified_tls_context())
                    code, _ = client.ehlo(configuration.helo_name or "")
                    if code >= 400:
                        return ProviderValidationResult(
                            ProviderValidationStatus.INVALID,
                            "smtp_post_tls_ehlo_rejected",
                        )
                if configuration.username is not None:
                    if password is None:
                        return ProviderValidationResult(
                            ProviderValidationStatus.INVALID,
                            "smtp_password_required",
                        )
                    client.login(configuration.username, password)
        except smtplib.SMTPAuthenticationError:
            return ProviderValidationResult(
                ProviderValidationStatus.INVALID,
                "smtp_authentication_rejected",
            )
        except (
            smtplib.SMTPNotSupportedError,
            ssl.SSLCertVerificationError,
        ):
            return ProviderValidationResult(
                ProviderValidationStatus.INVALID,
                "smtp_security_incompatible",
            )
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected):
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "smtp_temporarily_unavailable",
            )
        except smtplib.SMTPException:
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "smtp_protocol_unavailable",
            )
        except (TimeoutError, OSError):
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "smtp_temporarily_unavailable",
            )
        return ProviderValidationResult(
            ProviderValidationStatus.VALID,
            "smtp_valid",
        )


class SmtplibProviderTester(SmtpProviderTester):
    async def test(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> ProviderTestResult:
        return await asyncio.to_thread(
            self._test_blocking,
            configuration,
            password,
            destination,
            idempotency_key,
        )

    @staticmethod
    def _test_blocking(
        configuration: SmtpConfiguration,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> ProviderTestResult:
        if "@" not in destination:
            return ProviderTestResult(
                ProviderTestOutcome.FAILED,
                "smtp_test_destination_invalid",
            )

        message = EmailMessage()
        message["From"] = configuration.sender
        message["To"] = destination
        message["Subject"] = "Request Engine SMTP configuration test"
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<p7-{digest}@request-engine>"
        message.set_content(
            "This message confirms that the configured Request Engine SMTP provider "
            "accepted a controlled test delivery."
        )

        transmission_started = False
        try:
            with _connect(configuration) as client:
                client.ehlo(configuration.helo_name or "")
                if configuration.security is SmtpSecurityMode.STARTTLS:
                    client.starttls(context=_verified_tls_context())
                    client.ehlo(configuration.helo_name or "")
                if configuration.username is not None:
                    if password is None:
                        return ProviderTestResult(
                            ProviderTestOutcome.FAILED,
                            "smtp_password_required",
                        )
                    client.login(configuration.username, password)
                transmission_started = True
                client.send_message(message)
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPNotSupportedError,
            ssl.SSLCertVerificationError,
        ):
            return ProviderTestResult(
                ProviderTestOutcome.FAILED,
                "smtp_test_rejected",
            )
        except smtplib.SMTPException:
            if transmission_started:
                return ProviderTestResult(
                    ProviderTestOutcome.UNKNOWN,
                    "smtp_test_delivery_unknown",
                )
            return ProviderTestResult(
                ProviderTestOutcome.FAILED,
                "smtp_test_unavailable",
            )
        except (TimeoutError, OSError):
            if transmission_started:
                return ProviderTestResult(
                    ProviderTestOutcome.UNKNOWN,
                    "smtp_test_delivery_unknown",
                )
            return ProviderTestResult(
                ProviderTestOutcome.FAILED,
                "smtp_test_unavailable",
            )
        return ProviderTestResult(
            ProviderTestOutcome.DELIVERED,
            "smtp_test_delivered",
        )
