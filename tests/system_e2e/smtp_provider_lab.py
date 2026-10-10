"""Test-only authenticated STARTTLS provider with an independent receipt API.

The server never writes message bodies or credentials to disk/logs. Its HTTP
control API is intended only for isolated E2E networks; it must never be
published outside the test environment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import hmac
import ipaddress
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session

_BEHAVIORS = {"accept", "reject_transient", "reject_permanent", "accept_then_drop"}


class _State:
    def __init__(self, username: str, password: str, control_token: str) -> None:
        self.username = username
        self.password = password
        self.control_token = control_token
        self.behavior = "accept"
        self.auth_attempts: list[dict[str, object]] = []
        self.data_attempts: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []
        self.lock = threading.RLock()

    def authenticate(self, mechanism: str, login: bytes, password: bytes) -> bool:
        valid = (
            login.decode("utf-8", errors="replace") == self.username
            and password.decode("utf-8", errors="replace") == self.password
        )
        with self.lock:
            self.auth_attempts.append({"mechanism": mechanism, "accepted": valid})
        return valid

    def snapshot(self, collection: str) -> list[dict[str, object]]:
        with self.lock:
            return [dict(item) for item in getattr(self, collection)]

    def configure(self, behavior: str) -> None:
        if behavior not in _BEHAVIORS:
            raise ValueError("unsupported SMTP lab behavior")
        with self.lock:
            self.behavior = behavior

    def record_data(self, server: SMTP, envelope: Envelope) -> str:
        raw = envelope.original_content or b""
        parsed = email.message_from_bytes(raw)
        raw_message_id = cast(object, parsed.get("Message-ID"))
        message_id = raw_message_id if isinstance(raw_message_id, str) else ""
        with self.lock:
            behavior = self.behavior
            smtp_code = {
                "reject_transient": 451,
                "reject_permanent": 550,
                "accept": 250,
                "accept_then_drop": None,
            }[behavior]
            attempt: dict[str, object] = {
                "message_id": message_id,
                "behavior": behavior,
                "smtp_code": smtp_code,
                "accepted": behavior in {"accept", "accept_then_drop"},
            }
            self.data_attempts.append(attempt)
            if attempt["accepted"]:
                # Record only the receipt fields required by the independent
                # oracle. Message content can include a recovery secret.
                self.messages.append(
                    {
                        "message_id": message_id,
                        "subject": _message_header(parsed, "Subject"),
                        "sender": envelope.mail_from,
                        "to": list(envelope.rcpt_tos),
                    }
                )
        if behavior == "reject_transient":
            return "451 4.3.0 temporary test-provider rejection"
        if behavior == "reject_permanent":
            return "550 5.7.1 permanent test-provider rejection"
        if behavior == "accept_then_drop":
            # The message is recorded as accepted before closing the transport;
            # the client cannot distinguish this from a lost message unless it
            # queries the independent receipt API.
            transport = server.transport
            if transport is None:
                raise RuntimeError("SMTP lab connection closed before simulated final reply loss")
            transport.close()
            return "250 queued"
        return "250 queued"

    def reset(self) -> None:
        with self.lock:
            self.behavior = "accept"
            self.auth_attempts.clear()
            self.data_attempts.clear()
            self.messages.clear()


def _message_header(message: Any, name: str) -> str:
    value = cast(object, message.get(name))
    return value if isinstance(value, str) else ""


def _generate_local_pki(directory: Path, hostname: str) -> tuple[Path, Path, Path]:
    """Generate a throw-away local CA/server identity for focused integration tests."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    directory.mkdir(parents=True, exist_ok=True)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Request Engine SMTP lab CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
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
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    san: list[x509.GeneralName] = [x509.DNSName(hostname), x509.DNSName("localhost")]
    san.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
                ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = directory / "ca.pem"
    cert_path = directory / "server.pem"
    key_path = directory / "server.key"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return ca_path, cert_path, key_path


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _make_handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                _json_response(self, 200, {"status": "ok"})
            elif self.path == "/messages":
                _json_response(self, 200, {"messages": state.snapshot("messages")})
            elif self.path == "/attempts":
                _json_response(
                    self,
                    200,
                    {
                        "auth_attempts": state.snapshot("auth_attempts"),
                        "data_attempts": state.snapshot("data_attempts"),
                    },
                )
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            supplied_token = self.headers.get("X-SMTP-Lab-Control", "")
            if not hmac.compare_digest(supplied_token, state.control_token):
                _json_response(self, 403, {"error": "forbidden"})
                return
            if self.path == "/control/reset":
                state.reset()
                _json_response(self, 200, {"reset": True})
                return
            if self.path != "/control/behavior":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload: object = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
                return
            if not isinstance(payload, dict):
                self.send_error(422)
                return
            control_payload = cast(dict[str, object], payload)
            behavior = control_payload.get("behavior")
            if not isinstance(behavior, str):
                self.send_error(422)
                return
            try:
                state.configure(behavior)
            except ValueError:
                self.send_error(422)
                return
            _json_response(self, 200, {"behavior": state.behavior})

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return Handler


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smtp-host", default=os.environ.get("SMTP_LAB_HOST", "0.0.0.0"))
    parser.add_argument(
        "--smtp-port", type=int, default=int(os.environ.get("SMTP_LAB_PORT", "1025"))
    )
    parser.add_argument("--http-host", default=os.environ.get("SMTP_LAB_HTTP_HOST", "0.0.0.0"))
    parser.add_argument(
        "--http-port", type=int, default=int(os.environ.get("SMTP_LAB_HTTP_PORT", "8091"))
    )
    cert_file_default = os.environ.get("SMTP_LAB_CERT_FILE")
    key_file_default = os.environ.get("SMTP_LAB_KEY_FILE")
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=None if cert_file_default is None else Path(cert_file_default),
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=None if key_file_default is None else Path(key_file_default),
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=Path(os.environ.get("SMTP_LAB_CERT_DIR", "/tmp/smtp-lab-tls")),
    )
    parser.add_argument("--username", default=os.environ.get("SMTP_LAB_USERNAME", "smtp-lab-user"))
    parser.add_argument(
        "--password", default=os.environ.get("SMTP_LAB_PASSWORD", "smtp-lab-test-password")
    )
    parser.add_argument(
        "--control-token",
        default=os.environ.get("SMTP_LAB_CONTROL_TOKEN", "smtp-lab-control-only"),
    )
    args = parser.parse_args()

    cert_file, key_file = args.cert_file, args.key_file
    if cert_file is None or key_file is None:
        _ca_file, cert_file, key_file = _generate_local_pki(args.cert_dir, "localhost")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_file), str(key_file))
    state = _State(args.username, args.password, args.control_token)
    smtp = Controller(
        _DataHandler(state),
        hostname=args.smtp_host,
        port=args.smtp_port,
        tls_context=context,
        require_starttls=True,
        auth_required=True,
        auth_require_tls=True,
        auth_callback=state.authenticate,
    )
    smtp.start()
    http = ThreadingHTTPServer((args.http_host, args.http_port), _make_handler(state))
    try:
        http.serve_forever()
    finally:
        http.shutdown()
        smtp.stop()


class _DataHandler:
    def __init__(self, state: _State) -> None:
        self._state = state

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        del session
        return self._state.record_data(server, envelope)


if __name__ == "__main__":
    run()
