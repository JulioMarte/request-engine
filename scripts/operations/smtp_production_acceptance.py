#!/usr/bin/env python3
"""Run controlled P7 SMTP production-provider acceptance without persisting secrets."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import math
import os
import subprocess
import uuid
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


def _require_evidence_reference(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise SmtpAcceptanceError(f"production acceptance requires {label} evidence reference")
    reference = value.strip()
    if not reference:
        raise SmtpAcceptanceError(f"production acceptance requires {label} evidence reference")
    return reference


def _resolve_dns(host: str, port: int, *, timeout_seconds: float = 5.0) -> tuple[str, ...]:
    del port  # getent resolves addresses; SMTP connects using the configured port.
    try:
        result = subprocess.run(
            ["getent", "ahosts", host],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SmtpAcceptanceError("SMTP DNS resolution failed") from exc
    addresses: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        try:
            addresses.add(str(ipaddress.ip_address(parts[0])))
        except ValueError:
            continue
    if not addresses:
        raise SmtpAcceptanceError("SMTP DNS resolution returned no addresses")
    return tuple(addresses)


def _validate_configuration(configuration: SmtpConfiguration) -> None:
    timeout = configuration.timeout_seconds
    try:
        valid_timeout = (
            not isinstance(timeout, bool) and math.isfinite(float(timeout)) and 0 < timeout <= 30
        )
    except (OverflowError, TypeError, ValueError):
        valid_timeout = False
    if not valid_timeout:
        raise SmtpAcceptanceError("SMTP timeout must be greater than 0 and at most 30 seconds")
    if configuration.security is SmtpSecurityMode.PLAIN:
        raise SmtpAcceptanceError("production SMTP acceptance requires TLS or STARTTLS")
    if configuration.username is None:
        raise SmtpAcceptanceError("production SMTP acceptance requires authenticated SMTP")


async def run_acceptance(
    *,
    configuration: SmtpConfiguration,
    password: str,
    destination: str,
    idempotency_key: str,
    throttling_evidence_reference: str,
    send_id: str | None = None,
) -> dict[str, Any]:
    _validate_configuration(configuration)
    if not math.isfinite(configuration.timeout_seconds):
        raise SmtpAcceptanceError("SMTP timeout must be finite")
    throttle_ref = _require_evidence_reference(
        throttling_evidence_reference,
        label="a throttling/error-behavior",
    )
    unique_send_id = send_id or str(uuid.uuid4())
    try:
        unique_send_id = str(uuid.UUID(unique_send_id))
    except (ValueError, AttributeError) as exc:
        raise SmtpAcceptanceError("send ID must be a UUID") from exc
    addresses = _resolve_dns(
        configuration.host,
        configuration.port,
        timeout_seconds=min(configuration.timeout_seconds, 5.0),
    )

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
        # A new unique provider Message-ID prevents a rerun from reusing an
        # earlier delivery identity. The supplied key is retained only as an
        # operator correlation label and never triggers automatic retries.
        idempotency_key=unique_send_id,
    )
    if delivery.outcome is ProviderTestOutcome.UNKNOWN:
        return {
            "schema": "request-engine/smtp-send-evidence/v1",
            "outcome": "submission_unknown_do_not_retry",
            "sent_at": datetime.now(UTC).isoformat(),
            "send_id": unique_send_id,
            "operator_correlation_key": idempotency_key,
            "message_id": (
                f"<p7-{hashlib.sha256(unique_send_id.encode('utf-8')).hexdigest()}@request-engine>"
            ),
            "host": configuration.host,
            "port": configuration.port,
            "security": configuration.security.value,
            "authenticated": True,
            "dns_addresses": list(addresses),
            "validation": {
                "status": validation.status.value,
                "detail_code": validation.detail_code,
            },
            "smtp_submission": {
                "outcome": delivery.outcome.value,
                "detail_code": delivery.detail_code,
            },
            "throttling_evidence_reference": throttle_ref,
            "credentials_persisted": False,
        }
    if delivery.outcome is not ProviderTestOutcome.DELIVERED:
        raise SmtpAcceptanceError(
            f"controlled SMTP submission was not accepted: {delivery.detail_code}"
        )

    return {
        "schema": "request-engine/smtp-send-evidence/v1",
        "outcome": "submission_accepted_pending_mailbox_verification",
        "sent_at": datetime.now(UTC).isoformat(),
        "send_id": unique_send_id,
        "operator_correlation_key": idempotency_key,
        "message_id": (
            f"<p7-{hashlib.sha256(unique_send_id.encode('utf-8')).hexdigest()}@request-engine>"
        ),
        "host": configuration.host,
        "port": configuration.port,
        "security": configuration.security.value,
        "authenticated": True,
        "dns_addresses": list(addresses),
        "validation": {
            "status": validation.status.value,
            "detail_code": validation.detail_code,
        },
        "smtp_submission": {
            "outcome": delivery.outcome.value,
            "detail_code": delivery.detail_code,
        },
        "throttling_evidence_reference": throttle_ref,
        "credentials_persisted": False,
    }


def verify_mailbox_receipt(
    send_evidence: dict[str, Any], reference: str, observed_message_id: str
) -> dict[str, Any]:
    """Promote a pending send only after an operator observes its exact Message-ID."""
    if send_evidence.get("schema") != "request-engine/smtp-send-evidence/v1":
        raise SmtpAcceptanceError("unsupported SMTP send evidence schema")
    if send_evidence.get("outcome") != "submission_accepted_pending_mailbox_verification":
        raise SmtpAcceptanceError("SMTP send evidence is not pending mailbox verification")
    send_id = send_evidence.get("send_id")
    message_id = send_evidence.get("message_id")
    receipt = _require_evidence_reference(reference, label="an observed mailbox receipt")
    if not isinstance(observed_message_id, str):
        raise SmtpAcceptanceError("observed mailbox Message-ID is required")
    if not isinstance(send_id, str) or not isinstance(message_id, str):
        raise SmtpAcceptanceError("SMTP send evidence lacks its unique send ID")
    try:
        canonical_send_id = str(uuid.UUID(send_id))
    except ValueError as exc:
        raise SmtpAcceptanceError("SMTP send evidence has an invalid send ID") from exc
    expected_message_id = (
        f"<p7-{hashlib.sha256(canonical_send_id.encode('utf-8')).hexdigest()}@request-engine>"
    )
    if message_id != expected_message_id:
        raise SmtpAcceptanceError("SMTP Message-ID does not match the recorded send ID")
    if not observed_message_id.strip() or observed_message_id.strip() != message_id:
        raise SmtpAcceptanceError("observed mailbox Message-ID does not match the send evidence")
    if (
        send_evidence.get("authenticated") is not True
        or send_evidence.get("credentials_persisted") is not False
        or send_evidence.get("security") not in {"tls", "starttls"}
        or not isinstance(send_evidence.get("dns_addresses"), list)
        or not send_evidence["dns_addresses"]
        or not isinstance(send_evidence.get("validation"), dict)
        or send_evidence["validation"].get("status") != "valid"
        or not isinstance(send_evidence.get("smtp_submission"), dict)
        or send_evidence["smtp_submission"].get("outcome") != "delivered"
    ):
        raise SmtpAcceptanceError("SMTP send evidence is incomplete")
    for field in ("host", "port", "security", "throttling_evidence_reference"):
        if field not in send_evidence or send_evidence[field] in (None, ""):
            raise SmtpAcceptanceError(f"SMTP send evidence is missing {field}")
    return {
        "schema": "request-engine/smtp-production-acceptance/v1",
        "outcome": "accepted",
        "completed_at": datetime.now(UTC).isoformat(),
        "send_id": send_id,
        "message_id": message_id,
        "host": send_evidence["host"],
        "port": send_evidence["port"],
        "security": send_evidence["security"],
        "authenticated": send_evidence["authenticated"],
        "dns_addresses": send_evidence["dns_addresses"],
        "validation": send_evidence["validation"],
        "smtp_submission": send_evidence["smtp_submission"],
        "delivery_evidence_reference": receipt,
        "throttling_evidence_reference": send_evidence["throttling_evidence_reference"],
        "credentials_persisted": False,
    }


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    required_fields = (
        "host",
        "port",
        "sender",
        "username",
        "security",
        "destination",
        "idempotency_key",
    )
    for field in required_fields:
        if getattr(args, field) in (None, ""):
            raise SmtpAcceptanceError(f"--{field.replace('_', '-')} is required for SMTP send")
    if not args.throttling_evidence_reference:
        raise SmtpAcceptanceError("--throttling-evidence-reference is required for SMTP send")
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
        send_id=args.send_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--sender")
    parser.add_argument("--username")
    parser.add_argument("--security", choices=("tls", "starttls"))
    parser.add_argument("--destination")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--password-env", default="REQUEST_ENGINE_SMTP_ACCEPTANCE_PASSWORD")
    parser.add_argument("--helo-name")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--throttling-evidence-reference")
    parser.add_argument("--send-id", help="unique UUID; generated when omitted")
    parser.add_argument("--delivery-evidence-reference", help="use with --verify-send-evidence")
    parser.add_argument("--observed-message-id", help="exact Message-ID observed in the mailbox")
    parser.add_argument("--verify-send-evidence", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.verify_send_evidence is not None:
            source = json.loads(args.verify_send_evidence.read_text(encoding="utf-8"))
            if not isinstance(source, dict):
                raise SmtpAcceptanceError("SMTP send evidence must be a JSON object")
            if not args.observed_message_id:
                raise SmtpAcceptanceError(
                    "--observed-message-id is required for receipt verification"
                )
            evidence = verify_mailbox_receipt(
                source,
                args.delivery_evidence_reference or "",
                args.observed_message_id,
            )
        else:
            evidence = asyncio.run(_async_main(args))
    except (SmtpAcceptanceError, ValueError) as exc:
        raise SystemExit(f"SMTP production acceptance failed: {exc}") from exc
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 2 if evidence.get("outcome") == "submission_unknown_do_not_retry" else 0


if __name__ == "__main__":
    raise SystemExit(main())
