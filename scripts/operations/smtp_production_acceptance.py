#!/usr/bin/env python3
"""Run controlled P7 SMTP production-provider acceptance without persisting secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from request_engine.modules.platform_configuration.adapters.smtp import (
    SmtplibConfigurationValidator,
    SmtplibProviderTester,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderTestOutcome,
    ProviderValidationStatus,
    SmtpConfiguration,
    SmtpSecurityMode,
)


class SmtpAcceptanceError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise SmtpAcceptanceError(f"required environment variable is missing: {name}")
    return value


def _require_throttling_reference(value: str) -> str:
    reference = value.strip()
    if not reference:
        raise SmtpAcceptanceError(
            "production acceptance requires a throttling/error-behavior evidence reference"
        )
    return reference


def _resolve_dns(host: str, port: int) -> tuple[str, ...]:
    try:
        values = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SmtpAcceptanceError("SMTP DNS resolution failed") from exc
    addresses = sorted({str(value[4][0]) for value in values})
    if not addresses:
        raise SmtpAcceptanceError("SMTP DNS resolution returned no addresses")
    return tuple(addresses)


async def run_acceptance(
    *,
    configuration: SmtpConfiguration,
    password: str,
    destination: str,
    idempotency_key: str,
    throttling_evidence_reference: str,
) -> dict[str, Any]:
    if configuration.security is SmtpSecurityMode.PLAIN:
        raise SmtpAcceptanceError("production SMTP acceptance requires TLS or STARTTLS")
    if configuration.username is None:
        raise SmtpAcceptanceError("production SMTP acceptance requires authenticated SMTP")
    throttle_ref = _require_throttling_reference(throttling_evidence_reference)
    addresses = _resolve_dns(configuration.host, configuration.port)

    validator = SmtplibConfigurationValidator()
    validation = await validator.validate(configuration, password=password)
    if validation.status is not ProviderValidationStatus.VALID:
        raise SmtpAcceptanceError(
            f"SMTP provider validation did not pass: {validation.detail_code}"
        )

    tester = SmtplibProviderTester()
    delivery = await tester.test(
        configuration,
        password=password,
        destination=destination,
        idempotency_key=idempotency_key,
    )
    if delivery.outcome is not ProviderTestOutcome.DELIVERED:
        raise SmtpAcceptanceError(
            f"controlled SMTP delivery was not confirmed: {delivery.detail_code}"
        )

    return {
        "schema": "request-engine/smtp-production-acceptance/v1",
        "outcome": "accepted",
        "completed_at": datetime.now(UTC).isoformat(),
        "host": configuration.host,
        "port": configuration.port,
        "security": configuration.security.value,
        "authenticated": True,
        "dns_addresses": list(addresses),
        "validation": {
            "status": validation.status.value,
            "detail_code": validation.detail_code,
        },
        "controlled_delivery": {
            "outcome": delivery.outcome.value,
            "detail_code": delivery.detail_code,
        },
        "throttling_evidence_reference": throttle_ref,
        "credentials_persisted": False,
    }


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    try:
        security = SmtpSecurityMode(args.security)
    except ValueError as exc:
        raise SmtpAcceptanceError("security must be tls or starttls") from exc
    configuration = SmtpConfiguration(
        host=args.host,
        port=args.port,
        sender=args.sender,
        security=security,
        username=args.username,
        timeout_seconds=args.timeout_seconds,
        helo_name=args.helo_name,
    )
    password = _required_env(args.password_env)
    return await run_acceptance(
        configuration=configuration,
        password=password,
        destination=args.destination,
        idempotency_key=args.idempotency_key,
        throttling_evidence_reference=args.throttling_evidence_reference,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--sender", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--security", choices=("tls", "starttls"), required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--password-env", default="REQUEST_ENGINE_SMTP_ACCEPTANCE_PASSWORD")
    parser.add_argument("--helo-name")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--throttling-evidence-reference", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        evidence = asyncio.run(_async_main(args))
    except (SmtpAcceptanceError, ValueError) as exc:
        raise SystemExit(f"SMTP production acceptance failed: {exc}") from exc
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
