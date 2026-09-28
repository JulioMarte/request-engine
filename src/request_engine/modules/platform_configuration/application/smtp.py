from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SmtpSecurityMode(StrEnum):
    STARTTLS = "starttls"
    TLS = "tls"
    PLAIN = "plain"


@dataclass(frozen=True, slots=True)
class SmtpConfiguration:
    host: str
    port: int
    sender: str
    security: SmtpSecurityMode
    username: str | None = None
    timeout_seconds: float = 10.0
    helo_name: str | None = None

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("SMTP host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("SMTP port must be between 1 and 65535")
        if not self.sender.strip() or "@" not in self.sender:
            raise ValueError("SMTP sender must be an email address")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("SMTP timeout must be between 0 and 60 seconds")
        if self.username is not None and not self.username.strip():
            raise ValueError("SMTP username cannot be blank")
        if self.helo_name is not None and not self.helo_name.strip():
            raise ValueError("SMTP HELO name cannot be blank")


class ProviderValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProviderValidationResult:
    status: ProviderValidationStatus
    detail_code: str


class SmtpConfigurationValidator(Protocol):
    async def validate(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
    ) -> ProviderValidationResult: ...


def parse_smtp_configuration(payload: dict[str, object]) -> SmtpConfiguration:
    allowed = {
        "host",
        "port",
        "sender",
        "security",
        "username",
        "timeout_seconds",
        "helo_name",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unsupported SMTP configuration fields: {sorted(unknown)}")

    host_raw = payload.get("host")
    port_raw = payload.get("port")
    sender_raw = payload.get("sender")
    security_raw = payload.get("security")
    username_raw = payload.get("username")
    timeout_raw = payload.get("timeout_seconds", 10.0)
    helo_raw = payload.get("helo_name")

    if not isinstance(host_raw, str):
        raise ValueError("SMTP host must be a string")
    if not isinstance(port_raw, int) or isinstance(port_raw, bool):
        raise ValueError("SMTP port must be an integer")
    if not isinstance(sender_raw, str):
        raise ValueError("SMTP sender must be a string")
    if not isinstance(security_raw, str):
        raise ValueError("SMTP security mode must be a string")
    if username_raw is not None and not isinstance(username_raw, str):
        raise ValueError("SMTP username must be a string")
    if not isinstance(timeout_raw, (int, float)) or isinstance(timeout_raw, bool):
        raise ValueError("SMTP timeout must be numeric")
    if helo_raw is not None and not isinstance(helo_raw, str):
        raise ValueError("SMTP HELO name must be a string")

    try:
        security = SmtpSecurityMode(security_raw)
    except ValueError as exc:
        raise ValueError("SMTP security mode is invalid") from exc

    return SmtpConfiguration(
        host=host_raw,
        port=port_raw,
        sender=sender_raw,
        security=security,
        username=username_raw,
        timeout_seconds=float(timeout_raw),
        helo_name=helo_raw,
    )


class ProviderTestOutcome(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderTestResult:
    outcome: ProviderTestOutcome
    detail_code: str


class SmtpProviderTester(Protocol):
    async def test(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> ProviderTestResult: ...
