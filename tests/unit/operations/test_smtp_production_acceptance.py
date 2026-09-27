from __future__ import annotations

import importlib.util
import json
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


def _dns(_host: str, _port: int) -> tuple[str, ...]:
    return ("203.0.113.10",)


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
    )

    assert result["outcome"] == "accepted"
    assert result["authenticated"] is True
    assert result["credentials_persisted"] is False
    assert result["dns_addresses"] == ["203.0.113.10"]
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
        )
