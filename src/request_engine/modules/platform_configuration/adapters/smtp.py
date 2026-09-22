from __future__ import annotations

import asyncio
import smtplib
import ssl

from request_engine.modules.platform_configuration.application.smtp import (
    ProviderValidationResult,
    ProviderValidationStatus,
    SmtpConfiguration,
    SmtpConfigurationValidator,
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
