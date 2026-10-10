from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "network_probe",
    Path(__file__).resolve().parents[3] / "scripts/operations/network_acceptance_probe.py",
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def plan(port: int, *, expected: str = "reachable", protocol: str = "tcp") -> dict[str, Any]:
    return {
        "schema": "request-engine/network-plan/v1",
        "candidate": "test-sha",
        "configuration_reference": "config-1",
        "source_reference": "loopback-lab",
        "vantage": "public",
        "timeout_seconds": 0.2,
        "endpoints": [
            {
                "id": "control",
                "address": "127.0.0.1",
                "port": port,
                "protocol": protocol,
                "server_name": "localhost",
                "expected": expected,
            }
        ],
    }


@pytest.mark.unit
def test_open_private_tcp_listener_fails_public_isolation() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = module.run_plan(plan(listener.getsockname()[1], expected="blocked"))
    assert result["outcome"] == "failed"
    assert result["results"][0]["tcp_connected"] is True
    assert result["production_certified"] is False


@pytest.mark.unit
def test_closed_listener_is_observation_not_isolation_certification() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        # Bound but not listening: connection refused without a port-reuse race.
        result = module.run_plan(plan(port, expected="blocked"))
    assert result["outcome"] == "expectations_met"
    assert result["results"][0]["observation"] == "refused"
    assert result["requires_private_positive_baseline_and_firewall_review"] is True


@pytest.mark.unit
def test_tcp_handshake_then_tls_timeout_is_still_reachable() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = module.run_plan(
            plan(listener.getsockname()[1], expected="blocked", protocol="tls")
        )
    assert result["outcome"] == "failed"
    assert result["results"][0]["tcp_connected"] is True
    assert result["results"][0]["tls_verified"] is False


@pytest.mark.unit
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 10**400, 0, 11])
def test_rejects_invalid_timeout(value: Any) -> None:
    config = plan(443)
    config["timeout_seconds"] = value
    with pytest.raises(module.NetworkProbeError):
        module.validate_plan(config)


@pytest.mark.unit
@pytest.mark.parametrize("address", ["example.com", "127.0.0.1/path", "::g", None])
def test_dns_or_bad_address_cannot_be_negative_isolation_evidence(address: Any) -> None:
    config = plan(443)
    config["endpoints"][0]["address"] = address
    with pytest.raises(module.NetworkProbeError, match="literal"):
        module.validate_plan(config)


@pytest.mark.unit
def test_invalid_certificate_never_passes_as_blocked(tmp_path: Path) -> None:
    import ssl
    import threading
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / "untrusted.pem"
    key_file = tmp_path / "key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)

        def serve() -> None:
            with listener.accept()[0] as client:
                try:
                    with context.wrap_socket(client, server_side=True):
                        pass
                except ssl.SSLError:
                    pass  # Client rejects this untrusted certificate.

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            result = module.run_plan(
                plan(
                    listener.getsockname()[1],
                    expected="blocked",
                    protocol="tls",
                )
            )
        finally:
            thread.join(timeout=3)
        assert not thread.is_alive()
    assert result["outcome"] == "failed"
    assert result["results"][0]["tcp_connected"] is True
    assert result["results"][0]["tls_verified"] is False
    assert result["results"][0]["observation"] == "tls_error"
