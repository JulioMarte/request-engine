import hashlib
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

import pytest

from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.secrets.smtp_delivery_channel import (
    SmtpRecoveryDeliveryChannel,
)

pytestmark = [pytest.mark.unit]

_SECRET = "raw-recovery-proof-value"
_DESTINATION = "recover@example.test"
_KEY = "11111111-1111-1111-1111-111111111111:1"


class _RecordingSmtp(smtplib.SMTP):
    """Minimal SMTP double that records calls and never opens a socket."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.connection_args = args
        self.connection_kwargs = kwargs
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        self.connect_error: Exception | None = None
        self.send_error: Exception | None = None

    def __enter__(self) -> "_RecordingSmtp":
        self.calls.append("connect")
        if self.connect_error is not None:
            raise self.connect_error
        return self

    def __exit__(self, *args: Any) -> None:
        self.calls.append("close")

    def ehlo(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("ehlo")
        return (250, b"ok")

    def starttls(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("starttls")
        return (220, b"ready")

    def login(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("login")
        return (235, b"authenticated")

    def send_message(self, *args: Any, **kwargs: Any) -> dict[str, tuple[int, bytes]]:
        self.calls.append("send_message")
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(args[0])
        return {}


class _SmtpTransportDouble:
    def __init__(self) -> None:
        self.instances: list[_RecordingSmtp] = []
        self.connect_error: Exception | None = None
        self.send_error: Exception | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> smtplib.SMTP:
        instance = _RecordingSmtp(*args, **kwargs)
        instance.connect_error = self.connect_error
        instance.send_error = self.send_error
        self.instances.append(instance)
        return instance


def _channel(
    transport: _SmtpTransportDouble,
    *,
    reset_url: str | None = None,
) -> SmtpRecoveryDeliveryChannel:
    return SmtpRecoveryDeliveryChannel(
        host="smtp.example.test",
        port=587,
        sender="noreply@example.test",
        username="mailer",
        password="mailer-secret",
        reset_url=reset_url,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_send_delivers_with_deterministic_message_id_and_neutral_headers() -> None:
    transport = _SmtpTransportDouble()

    outcome = await _channel(transport).send(
        secret=_SECRET,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    assert outcome is DeliveryOutcome.DELIVERED
    instance = transport.instances[0]
    assert instance.connection_args[:2] == ("smtp.example.test", 587)
    assert instance.connection_kwargs["timeout"] == 10.0
    assert instance.calls == ["connect", "ehlo", "starttls", "login", "send_message", "close"]
    message = instance.sent[0]
    expected_message_id = hashlib.sha256(_KEY.encode("utf-8")).hexdigest()
    assert message["Message-ID"] == f"<{expected_message_id}@request-engine>"
    assert message["To"] == _DESTINATION
    assert message["Subject"] is not None
    assert _SECRET in str(message.get_content())
    for _name, value in message.items():
        assert _SECRET not in str(value)


@pytest.mark.asyncio
async def test_blank_optional_auth_values_do_not_attempt_smtp_authentication() -> None:
    transport = _SmtpTransportDouble()
    channel = SmtpRecoveryDeliveryChannel(
        host="mailpit",
        port=1025,
        sender="recovery@example.test",
        username="",
        password="",
        starttls=False,
        transport=transport,
    )

    outcome = await channel.send(
        secret=_SECRET,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    assert outcome is DeliveryOutcome.DELIVERED
    assert transport.instances[0].calls == ["connect", "ehlo", "send_message", "close"]


@pytest.mark.asyncio
async def test_starttls_not_supported_is_definitive_configuration_failure() -> None:
    class _NoStartTls(_RecordingSmtp):
        def starttls(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported")

    class _NoStartTlsTransport:
        def __call__(self, *args: Any, **kwargs: Any) -> smtplib.SMTP:
            return _NoStartTls(*args, **kwargs)

    channel = SmtpRecoveryDeliveryChannel(
        host="smtp.example.test",
        port=587,
        sender="noreply@example.test",
        starttls=True,
        transport=_NoStartTlsTransport(),
    )

    outcome = await channel.send(
        secret=_SECRET,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    assert outcome is DeliveryOutcome.FAILED


@pytest.mark.asyncio
async def test_reset_url_body_uses_fragment_with_quoted_token() -> None:
    transport = _SmtpTransportDouble()
    secret = "token with spaces/and+symbols"

    await _channel(transport, reset_url="https://app.example.test/recover").send(
        secret=secret,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    body = str(transport.instances[0].sent[0].get_content())
    assert f"https://app.example.test/recover#token={quote(secret, safe='')}" in body
    subject = transport.instances[0].sent[0]["Subject"]
    assert subject is not None
    assert secret not in subject


@pytest.mark.asyncio
async def test_recipients_refused_is_definitive_failure() -> None:
    transport = _SmtpTransportDouble()
    transport.send_error = smtplib.SMTPRecipientsRefused({})

    outcome = await _channel(transport).send(
        secret=_SECRET,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    assert outcome is DeliveryOutcome.FAILED


@pytest.mark.asyncio
async def test_connection_failure_before_transmission_is_retryable() -> None:
    transport = _SmtpTransportDouble()
    transport.connect_error = ConnectionRefusedError()

    with pytest.raises(RecoveryDeliveryRetryable):
        await _channel(transport).send(
            secret=_SECRET,
            destination_reference=_DESTINATION,
            idempotency_key=_KEY,
        )


@pytest.mark.asyncio
async def test_post_connect_disconnect_is_unknown() -> None:
    transport = _SmtpTransportDouble()
    transport.send_error = smtplib.SMTPServerDisconnected()

    outcome = await _channel(transport).send(
        secret=_SECRET,
        destination_reference=_DESTINATION,
        idempotency_key=_KEY,
    )

    assert outcome is DeliveryOutcome.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_has_no_smtp_query_surface() -> None:
    assert await _channel(_SmtpTransportDouble()).reconcile(idempotency_key=_KEY) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["", "   ", "not-an-address"])
async def test_invalid_destination_is_permanent(destination: str) -> None:
    transport = _SmtpTransportDouble()

    with pytest.raises(RecoveryDeliveryPermanent):
        await _channel(transport).send(
            secret=_SECRET,
            destination_reference=destination,
            idempotency_key=_KEY,
        )

    assert transport.instances == []
