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
        transport: type[smtplib.SMTP]
        transport = (
            smtplib.SMTP_SSL
            if configuration.security is SmtpSecurityMode.TLS
            else smtplib.SMTP
        )
        try:
            with transport(
                configuration.host,
                configuration.port,
                timeout=configuration.timeout_seconds,
            ) as client:
                code, _ = client.ehlo(configuration.helo_name)
                if code >= 400:
                    return ProviderValidationResult(
                        ProviderValidationStatus.INVALID,
                        "smtp_ehlo_rejected",
                    )
                if configuration.security is SmtpSecurityMode.STARTTLS:
                    client.starttls(context=ssl.create_default_context())
                    code, _ = client.ehlo(configuration.helo_name)
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
        except (TimeoutError, OSError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected):
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "smtp_temporarily_unavailable",
            )
        except smtplib.SMTPException:
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "smtp_protocol_unavailable",
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

        transport: type[smtplib.SMTP]
        transport = (
            smtplib.SMTP_SSL
            if configuration.security is SmtpSecurityMode.TLS
            else smtplib.SMTP
        )
        transmission_started = False
        try:
            with transport(
                configuration.host,
                configuration.port,
                timeout=configuration.timeout_seconds,
            ) as client:
                client.ehlo(configuration.helo_name)
                if configuration.security is SmtpSecurityMode.STARTTLS:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo(configuration.helo_name)
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
        except (TimeoutError, OSError, smtplib.SMTPException):
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
