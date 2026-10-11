from __future__ import annotations

import importlib.util
import json
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "smtp_production_acceptance",
    ROOT / "scripts/operations/smtp_production_acceptance.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class _Validator:
    async def validate(self, configuration: object, *, password: str | None) -> object:
        del configuration, password
        return SimpleNamespace(
            status=module.ProviderValidationStatus.VALID,
            detail_code="smtp_valid",
        )


class _Tester:
    async def test(
        self,
        configuration: object,
        *,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> object:
        del configuration, password, destination, idempotency_key
        return SimpleNamespace(
            outcome=module.ProviderTestOutcome.DELIVERED,
            detail_code="smtp_test_delivered",
        )


def _configuration(*, security: Any | None = None) -> Any:
    return module.SmtpConfiguration(
        host="smtp.example.test",
        port=587,
        sender="noreply@example.test",
        security=security or module.SmtpSecurityMode.STARTTLS,
        username="smtp-user",
    )


def _dns(_host: str, _port: int, **_kwargs: object) -> tuple[str, ...]:
    return ("203.0.113.10",)


def test_dns_preflight_uses_bounded_argument_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> object:
        observed["command"] = command
        observed.update(kwargs)
        return SimpleNamespace(stdout="203.0.113.10 STREAM smtp.example.test\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module._resolve_dns("smtp.example.test", 587, timeout_seconds=3.0) == ("203.0.113.10",)
    assert observed["command"] == ["getent", "ahosts", "smtp.example.test"]
    assert observed["timeout"] == 3.0
    assert observed["capture_output"] is True


@pytest.mark.asyncio
async def test_acceptance_emits_secret_free_real_provider_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_resolve_dns", _dns)
    monkeypatch.setattr(module, "SmtplibConfigurationValidator", _Validator)
    monkeypatch.setattr(module, "SmtplibProviderTester", _Tester)

    result = await module.run_acceptance(
        configuration=_configuration(),
        password="super-secret-password",
        destination="acceptance@example.test",
        idempotency_key="smtp-prod-acceptance-1",
        throttling_evidence_reference="provider-ticket-123",
        send_id="ef51e16c-1b7d-4e4e-9061-55f6ac655da1",
    )

    assert result["outcome"] == "submission_accepted_pending_mailbox_verification"
    assert result["send_id"] == "ef51e16c-1b7d-4e4e-9061-55f6ac655da1"
    assert result["authenticated"] is True
    assert result["credentials_persisted"] is False
    assert result["dns_addresses"] == ["203.0.113.10"]
    assert result["smtp_submission"]["outcome"] == "delivered"
    accepted = module.verify_mailbox_receipt(result, "mailbox-check-456", result["message_id"])
    assert accepted["outcome"] == "accepted"
    assert accepted["send_id"] == result["send_id"]
    assert accepted["message_id"] == result["message_id"]
    assert "super-secret-password" not in json.dumps(result)


@pytest.mark.asyncio
async def test_acceptance_rejects_plain_smtp() -> None:
    with pytest.raises(module.SmtpAcceptanceError, match="TLS or STARTTLS"):
        await module.run_acceptance(
            configuration=_configuration(security=module.SmtpSecurityMode.PLAIN),
            password="secret",
            destination="acceptance@example.test",
            idempotency_key="smtp-prod-acceptance-2",
            throttling_evidence_reference="provider-ticket-123",
            send_id=str(uuid.uuid4()),
        )


@pytest.mark.asyncio
async def test_acceptance_requires_throttling_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_resolve_dns", _dns)

    with pytest.raises(module.SmtpAcceptanceError, match="throttling"):
        await module.run_acceptance(
            configuration=_configuration(),
            password="secret",
            destination="acceptance@example.test",
            idempotency_key="smtp-prod-acceptance-3",
            throttling_evidence_reference="",
            send_id=str(uuid.uuid4()),
        )


def test_mailbox_verification_rejects_wrong_or_missing_send_receipt() -> None:
    with pytest.raises(module.SmtpAcceptanceError, match="schema"):
        module.verify_mailbox_receipt({"schema": "wrong"}, "mailbox-check", "<id>")
    with pytest.raises(module.SmtpAcceptanceError, match="mailbox receipt"):
        module.verify_mailbox_receipt(
            {
                "schema": "request-engine/smtp-send-evidence/v1",
                "outcome": "submission_accepted_pending_mailbox_verification",
                "send_id": str(uuid.uuid4()),
                "message_id": "<unique@example.test>",
            },
            "",
            "<unique@example.test>",
        )


@pytest.mark.asyncio
async def test_ambiguous_submission_is_reported_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "_resolve_dns", _dns)
    monkeypatch.setattr(module, "SmtplibConfigurationValidator", _Validator)

    class _UnknownTester:
        async def test(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                outcome=module.ProviderTestOutcome.UNKNOWN,
                detail_code="smtp_test_delivery_unknown",
            )

    monkeypatch.setattr(module, "SmtplibProviderTester", _UnknownTester)
    result = await module.run_acceptance(
        configuration=_configuration(),
        password="secret",
        destination="acceptance@example.test",
        idempotency_key="correlation",
        send_id="ef51e16c-1b7d-4e4e-9061-55f6ac655da1",
        throttling_evidence_reference="provider-ticket-123",
    )
    assert result["outcome"] == "submission_unknown_do_not_retry"
    assert result["send_id"] == "ef51e16c-1b7d-4e4e-9061-55f6ac655da1"


@pytest.mark.asyncio
async def test_public_acceptance_call_rejects_timeout_above_runner_bound() -> None:
    configuration = replace(_configuration(), timeout_seconds=45.0)
    with pytest.raises(module.SmtpAcceptanceError, match="timeout"):
        await module.run_acceptance(
            configuration=configuration,
            password="secret",
            destination="acceptance@example.test",
            idempotency_key="correlation",
            throttling_evidence_reference="provider-ticket-123",
        )
