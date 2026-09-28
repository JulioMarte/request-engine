"""Protocol conformance for the SMTP client surfaces against a real TLS server.

These proofs run a real RFC 5321 SMTP server (``aiosmtpd``) over real sockets
with real TLS handshakes and real ``AUTH``.  The only substitution is the trust
anchor: the server certificate is issued by a throw-away CA that the test makes
the client trust, exactly as a production host trusts a public/private CA.  The
handshake, certificate-chain verification and hostname verification are the real
production code paths.

The negative cases are the security proof: before the client passed a verifying
context to ``SMTP_SSL``/``starttls``, an untrusted certificate was silently
accepted.  These tests fail if that regression returns.
"""

from __future__ import annotations

import datetime
import email
import ipaddress
import socket
import ssl
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from email import policy
from pathlib import Path

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

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
from request_engine.platform.secrets.delivery import DeliveryOutcome
from request_engine.platform.secrets.smtp_delivery_channel import (
    SmtpRecoveryDeliveryChannel,
)

pytestmark = [
    pytest.mark.integration,
    # aiosmtpd warns when AUTH is required without a STARTTLS upgrade; the SMTPS
    # listener is already encrypted from the first byte, so the warning does not
    # apply to that server.
    pytest.mark.filterwarnings("ignore:Requiring AUTH while not requiring TLS:UserWarning"),
]

_USERNAME = "mailer"
_PASSWORD = "mailer-secret"
_SECRET = "raw-recovery-proof-value"
_DESTINATION = "recover@example.test"


@dataclass(frozen=True, slots=True)
class _Pki:
    ca_path: Path
    cert_path: Path
    key_path: Path


class _RecordingHandler:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        del server, session
        raw = envelope.original_content
        self.messages.append(raw if raw is not None else b"")
        return "250 Message accepted for delivery"


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _build_pki(directory: Path) -> _Pki:
    now = datetime.datetime.now(datetime.UTC)
    ca_key = _new_key()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Request Engine Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = _new_key()
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_path = directory / "ca.pem"
    cert_path = directory / "server.pem"
    key_path = directory / "server.key"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return _Pki(ca_path=ca_path, cert_path=cert_path, key_path=key_path)


@pytest.fixture(scope="module")
def smtp_pki(tmp_path_factory: pytest.TempPathFactory) -> _Pki:
    return _build_pki(tmp_path_factory.mktemp("smtp-pki"))


@pytest.fixture
def trusted_ca(smtp_pki: _Pki, monkeypatch: pytest.MonkeyPatch) -> _Pki:
    original = ssl.create_default_context

    def _trusted(*args: object, **kwargs: object) -> ssl.SSLContext:
        return original(cafile=str(smtp_pki.ca_path))

    monkeypatch.setattr(ssl, "create_default_context", _trusted)
    return smtp_pki


def _server_context(pki: _Pki) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(pki.cert_path), str(pki.key_path))
    return context


def _auth_callback(mechanism: str, login: bytes, password: bytes) -> bool:
    del mechanism
    return login == _USERNAME.encode() and password == _PASSWORD.encode()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _starttls_server(pki: _Pki) -> Generator[tuple[_RecordingHandler, int]]:
    handler = _RecordingHandler()
    port = _free_port()
    controller = Controller(
        handler,
        hostname="127.0.0.1",
        port=port,
        tls_context=_server_context(pki),
        require_starttls=True,
        auth_required=True,
        auth_require_tls=True,
        auth_callback=_auth_callback,
    )
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


@contextmanager
def _smtps_server(pki: _Pki) -> Generator[tuple[_RecordingHandler, int]]:
    handler = _RecordingHandler()
    port = _free_port()
    controller = Controller(
        handler,
        hostname="127.0.0.1",
        port=port,
        ssl_context=_server_context(pki),
        auth_required=True,
        # Implicit TLS is encrypted from the first byte, but aiosmtpd only marks
        # ``session.ssl`` after a STARTTLS upgrade, so it must not require that
        # upgrade to advertise AUTH on an SMTPS listener.
        auth_require_tls=False,
        auth_callback=_auth_callback,
    )
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


def _configuration(port: int, security: SmtpSecurityMode) -> SmtpConfiguration:
    return SmtpConfiguration(
        host="127.0.0.1",
        port=port,
        sender="noreply@example.test",
        security=security,
        username=_USERNAME,
        timeout_seconds=10,
    )


@pytest.mark.asyncio
@pytest.mark.contract
async def test_starttls_verifies_trusted_certificate_and_authenticates(
    trusted_ca: _Pki,
) -> None:
    with _starttls_server(trusted_ca) as (_handler, port):
        result = await SmtplibConfigurationValidator().validate(
            _configuration(port, SmtpSecurityMode.STARTTLS), password=_PASSWORD
        )

    assert result.status is ProviderValidationStatus.VALID
    assert result.detail_code == "smtp_valid"


@pytest.mark.asyncio
@pytest.mark.adversarial
async def test_starttls_rejects_untrusted_certificate(smtp_pki: _Pki) -> None:
    with _starttls_server(smtp_pki) as (_handler, port):
        result = await SmtplibConfigurationValidator().validate(
            _configuration(port, SmtpSecurityMode.STARTTLS), password=_PASSWORD
        )

    assert result.status is ProviderValidationStatus.INVALID
    assert result.detail_code == "smtp_security_incompatible"


@pytest.mark.asyncio
@pytest.mark.contract
async def test_implicit_tls_verifies_trusted_certificate_and_authenticates(
    trusted_ca: _Pki,
) -> None:
    with _smtps_server(trusted_ca) as (_handler, port):
        result = await SmtplibConfigurationValidator().validate(
            _configuration(port, SmtpSecurityMode.TLS), password=_PASSWORD
        )

    assert result.status is ProviderValidationStatus.VALID
    assert result.detail_code == "smtp_valid"


@pytest.mark.asyncio
@pytest.mark.adversarial
async def test_implicit_tls_rejects_untrusted_certificate(smtp_pki: _Pki) -> None:
    with _smtps_server(smtp_pki) as (_handler, port):
        result = await SmtplibConfigurationValidator().validate(
            _configuration(port, SmtpSecurityMode.TLS), password=_PASSWORD
        )

    assert result.status is ProviderValidationStatus.INVALID
    assert result.detail_code == "smtp_security_incompatible"


@pytest.mark.asyncio
@pytest.mark.contract
async def test_authentication_rejection_is_invalid_not_unavailable(trusted_ca: _Pki) -> None:
    with _starttls_server(trusted_ca) as (_handler, port):
        result = await SmtplibConfigurationValidator().validate(
            _configuration(port, SmtpSecurityMode.STARTTLS), password="wrong-password"
        )

    assert result.status is ProviderValidationStatus.INVALID
    assert result.detail_code == "smtp_authentication_rejected"


@pytest.mark.asyncio
@pytest.mark.contract
async def test_provider_test_delivers_message_over_verified_tls(trusted_ca: _Pki) -> None:
    with _starttls_server(trusted_ca) as (handler, port):
        result = await SmtplibProviderTester().test(
            _configuration(port, SmtpSecurityMode.STARTTLS),
            password=_PASSWORD,
            destination=_DESTINATION,
            idempotency_key="provider-test-key",
        )

    assert result.outcome is ProviderTestOutcome.DELIVERED
    assert result.detail_code == "smtp_test_delivered"
    assert len(handler.messages) == 1
    assert email.message_from_bytes(handler.messages[0])["To"] == _DESTINATION


@pytest.mark.asyncio
@pytest.mark.contract
async def test_recovery_channel_delivers_secret_over_verified_starttls(
    trusted_ca: _Pki,
) -> None:
    with _starttls_server(trusted_ca) as (handler, port):
        channel = SmtpRecoveryDeliveryChannel(
            host="127.0.0.1",
            port=port,
            sender="noreply@example.test",
            username=_USERNAME,
            password=_PASSWORD,
            starttls=True,
            timeout_seconds=10,
        )
        outcome = await channel.send(
            secret=_SECRET,
            destination_reference=_DESTINATION,
            idempotency_key="recovery-delivery-key",
        )

    assert outcome is DeliveryOutcome.DELIVERED
    assert len(handler.messages) == 1
    received = email.message_from_bytes(handler.messages[0], policy=policy.default)
    assert received["To"] == _DESTINATION
    assert _SECRET in received.get_content()
    for _name, value in received.items():
        assert _SECRET not in str(value)


@pytest.mark.asyncio
@pytest.mark.adversarial
async def test_recovery_channel_fails_closed_on_untrusted_certificate(smtp_pki: _Pki) -> None:
    with _starttls_server(smtp_pki) as (handler, port):
        channel = SmtpRecoveryDeliveryChannel(
            host="127.0.0.1",
            port=port,
            sender="noreply@example.test",
            username=_USERNAME,
            password=_PASSWORD,
            starttls=True,
            timeout_seconds=10,
        )
        outcome = await channel.send(
            secret=_SECRET,
            destination_reference=_DESTINATION,
            idempotency_key="recovery-delivery-key",
        )

    assert outcome is DeliveryOutcome.FAILED
    assert handler.messages == []
