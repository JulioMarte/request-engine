from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel

ROOT = Path(__file__).resolve().parents[2]
PROVIDER = ROOT / "tests/system_e2e/smtp_provider_lab.py"
ACCEPTANCE = ROOT / "scripts/operations/smtp_production_acceptance.py"


@dataclass(frozen=True)
class _Provider:
    process: subprocess.Popen[str]
    smtp_port: int
    http_port: int
    ca_path: Path
    password: str
    control_token: str

    @property
    def control_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(provider: _Provider, path: str, *, payload: dict[str, object] | None = None) -> object:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    if body is not None:
        headers["X-SMTP-Lab-Control"] = provider.control_token
    request = urllib.request.Request(
        f"{provider.control_url}{path}",
        data=body,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _reset(provider: _Provider, behavior: str = "accept") -> None:
    _request(provider, "/control/reset", payload={})
    if behavior != "accept":
        _request(provider, "/control/behavior", payload={"behavior": behavior})


def _snapshot(provider: _Provider, path: str) -> dict[str, object]:
    response = _request(provider, path)
    assert isinstance(response, dict)
    return cast(dict[str, object], response)


@pytest.fixture
def provider(tmp_path: Path) -> Iterator[_Provider]:
    smtp_port = _free_port()
    http_port = _free_port()
    cert_dir = tmp_path / "tls"
    password = "test-provider-password-only"
    env = os.environ.copy()
    env.update(
        {
            "SMTP_LAB_HOST": "127.0.0.1",
            "SMTP_LAB_PORT": str(smtp_port),
            "SMTP_LAB_HTTP_HOST": "127.0.0.1",
            "SMTP_LAB_HTTP_PORT": str(http_port),
            "SMTP_LAB_CERT_DIR": str(cert_dir),
            "SMTP_LAB_USERNAME": "smtp-lab-user",
            "SMTP_LAB_PASSWORD": password,
            "SMTP_LAB_CONTROL_TOKEN": "integration-control-token-only",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(PROVIDER)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    ca_path = cert_dir / "ca.pem"
    candidate = _Provider(
        process,
        smtp_port,
        http_port,
        ca_path,
        password,
        "integration-control-token-only",
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("SMTP provider lab exited during startup")
        try:
            response = _snapshot(candidate, "/health")
            if response.get("status") == "ok" and ca_path.exists():
                break
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.05)
    else:
        process.terminate()
        process.wait(timeout=5)
        raise TimeoutError("SMTP provider lab did not become ready")
    try:
        yield candidate
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _acceptance_command(provider: _Provider, output_path: Path) -> list[str]:
    return [
        sys.executable,
        str(ACCEPTANCE),
        "--host",
        "localhost",
        "--port",
        str(provider.smtp_port),
        "--sender",
        "acceptance@example.test",
        "--username",
        "smtp-lab-user",
        "--security",
        "starttls",
        "--destination",
        "receipt@example.test",
        "--idempotency-key",
        "smtp-provider-lab-run",
        "--password-env",
        "SMTP_LAB_PASSWORD",
        "--throttling-evidence-reference",
        "test-provider-simulated-response-modes",
        "--timeout-seconds",
        "3",
        "--output",
        str(output_path),
    ]


def _run_acceptance(
    provider: _Provider,
    output_path: Path,
    *,
    password: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SMTP_LAB_PASSWORD"] = provider.password if password is None else password
    env["SSL_CERT_FILE"] = str(provider.ca_path)
    return subprocess.run(
        _acceptance_command(provider, output_path),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.integration
def test_production_acceptance_cli_uses_real_starttls_auth_and_independent_receipts(
    provider: _Provider,
    tmp_path: Path,
) -> None:
    # Valid credentials traverse TCP, verified STARTTLS, AUTH, and DATA through
    # the production CLI. The independent receipt oracle is a separate HTTP API.
    accepted_path = tmp_path / "accepted.json"
    accepted = _run_acceptance(provider, accepted_path)
    assert accepted.returncode == 0, accepted.stderr
    accepted_evidence = json.loads(accepted_path.read_text(encoding="utf-8"))
    assert accepted_evidence["outcome"] == "submission_accepted_pending_mailbox_verification"
    assert accepted_evidence["authenticated"] is True
    assert provider.password not in accepted.stdout + accepted.stderr + accepted_path.read_text()
    receipt = _snapshot(provider, "/messages")
    messages = cast(list[dict[str, object]], receipt["messages"])
    assert len(messages) == 1
    assert messages[0]["message_id"] == accepted_evidence["message_id"]

    verified_path = tmp_path / "verified.json"
    verification = subprocess.run(
        [
            sys.executable,
            str(ACCEPTANCE),
            "--verify-send-evidence",
            str(accepted_path),
            "--observed-message-id",
            str(messages[0]["message_id"]),
            "--delivery-evidence-reference",
            "smtp-lab-independent-http-receipt",
            "--output",
            str(verified_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert verification.returncode == 0, verification.stderr
    promoted = json.loads(verified_path.read_text(encoding="utf-8"))
    assert promoted["outcome"] == "accepted"
    assert promoted["send_id"] == accepted_evidence["send_id"]

    # Invalid credentials fail before DATA and cannot produce a receipt.
    _reset(provider)
    invalid = _run_acceptance(provider, tmp_path / "invalid.json", password="incorrect")
    assert invalid.returncode != 0
    assert "incorrect" not in invalid.stdout + invalid.stderr
    invalid_attempts = _snapshot(provider, "/attempts")
    assert invalid_attempts["data_attempts"] == []
    assert _snapshot(provider, "/messages")["messages"] == []

    for behavior, expected_code in (
        ("reject_transient", 451),
        ("reject_permanent", 550),
    ):
        _reset(provider, behavior)
        rejected = _run_acceptance(provider, tmp_path / f"{behavior}.json")
        assert rejected.returncode != 0
        attempts = _snapshot(provider, "/attempts")
        data_attempts = cast(list[dict[str, object]], attempts["data_attempts"])
        assert len(data_attempts) == 1
        assert data_attempts[0]["smtp_code"] == expected_code
        assert data_attempts[0]["accepted"] is False
        assert _snapshot(provider, "/messages")["messages"] == []

    # The test provider stores the message, then drops the SMTP connection
    # instead of returning 250. The CLI persists UNKNOWN with its send ID; one
    # API receipt proves acceptance, and there is exactly one DATA attempt.
    _reset(provider, "accept_then_drop")
    unknown_path = tmp_path / "unknown.json"
    unknown = _run_acceptance(provider, unknown_path)
    assert unknown.returncode == 2
    unknown_evidence = json.loads(unknown_path.read_text(encoding="utf-8"))
    assert unknown_evidence["outcome"] == "submission_unknown_do_not_retry"
    assert unknown_evidence["send_id"]
    unknown_receipt = _snapshot(provider, "/messages")
    unknown_messages = cast(list[dict[str, object]], unknown_receipt["messages"])
    assert len(unknown_messages) == 1
    assert unknown_messages[0]["message_id"] == unknown_evidence["message_id"]
    unknown_attempts = _snapshot(provider, "/attempts")
    assert len(cast(list[object], unknown_attempts["data_attempts"])) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recovery_adapter_distinguishes_known_data_rejection_from_ambiguity(
    provider: _Provider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(provider.ca_path))

    def channel() -> SmtpRecoveryDeliveryChannel:
        return SmtpRecoveryDeliveryChannel(
            host="localhost",
            port=provider.smtp_port,
            sender="recovery@example.test",
            username="smtp-lab-user",
            password=provider.password,
            starttls=True,
            timeout_seconds=3,
        )

    _reset(provider, "reject_transient")
    with pytest.raises(RecoveryDeliveryRetryable):
        await channel().send(
            secret="test-proof",
            destination_reference="recipient@example.test",
            idempotency_key="smtp-lab-transient",
        )
    transient = _snapshot(provider, "/attempts")
    transient_data = cast(list[dict[str, object]], transient["data_attempts"])
    assert len(transient_data) == 1 and transient_data[0]["smtp_code"] == 451
    assert transient_data[0]["accepted"] is False

    _reset(provider, "reject_permanent")
    permanent = await channel().send(
        secret="test-proof",
        destination_reference="recipient@example.test",
        idempotency_key="smtp-lab-permanent",
    )
    assert permanent is DeliveryOutcome.FAILED
    permanent_attempts = _snapshot(provider, "/attempts")
    permanent_data = cast(list[dict[str, object]], permanent_attempts["data_attempts"])
    assert len(permanent_data) == 1 and permanent_data[0]["smtp_code"] == 550
    assert permanent_data[0]["accepted"] is False

    _reset(provider, "accept_then_drop")
    ambiguous = await channel().send(
        secret="test-proof",
        destination_reference="recipient@example.test",
        idempotency_key="smtp-lab-ambiguous",
    )
    assert ambiguous is DeliveryOutcome.UNKNOWN
    receipt = _snapshot(provider, "/messages")
    messages = cast(list[dict[str, object]], receipt["messages"])
    assert len(messages) == 1
    attempts = _snapshot(provider, "/attempts")
    data_attempts = cast(list[object], attempts["data_attempts"])
    assert len(data_attempts) == 1
