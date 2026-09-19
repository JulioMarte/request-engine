"""SMTP delivery channel for governed identity recovery secrets.

The channel is a projection of the technical delivery boundary: the raw proof
is placed only in the message body and the outcome distinguishes a definitive
provider rejection from a connection failure that never transmitted anything
and from an ambiguous post-connect failure that must not be retried blindly.
"""

import asyncio
import hashlib
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from urllib.parse import quote

from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)

_SUBJECT = "Request Engine identity recovery"


class SmtpRecoveryDeliveryChannel:
    """Send a recovery proof over SMTP with a deterministic Message-ID."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        use_ssl: bool = False,
        timeout_seconds: float = 10.0,
        reset_url: str | None = None,
        transport: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        if not host.strip():
            raise ValueError("smtp host is required")
        if port <= 0:
            raise ValueError("smtp port must be positive")
        if not sender.strip():
            raise ValueError("smtp sender is required")
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username.strip() if username is not None and username.strip() else None
        self._password = password if password is not None and password.strip() else None
        self._starttls = starttls
        self._use_ssl = use_ssl
        self._timeout_seconds = timeout_seconds
        self._reset_url = reset_url
        self._transport: Callable[..., smtplib.SMTP] = transport or (
            smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        )

    async def send(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        if not destination_reference.strip() or "@" not in destination_reference:
            raise RecoveryDeliveryPermanent("recovery destination is not a deliverable address")
        message = self._build_message(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )
        return await asyncio.to_thread(self._deliver_blocking, message)

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None:
        """SMTP exposes no delivery-query surface, so reconciliation is impossible.

        A connection-phase failure raises ``RecoveryDeliveryRetryable`` because
        nothing was transmitted. Any post-connect failure is reported as
        ``DeliveryOutcome.UNKNOWN``: the message may already have been accepted
        by the server, so it is never silently republished under the same key.
        """

        return None

    def _build_message(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = destination_reference
        message["Subject"] = _SUBJECT
        message_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<{message_id}@request-engine>"
        if self._reset_url is not None:
            link = f"{self._reset_url}#token={quote(secret, safe='')}"
            body = (
                "A recovery proof was requested for this address.\n\n"
                f"Open the following link to continue:\n{link}\n"
            )
        else:
            body = f"A recovery proof was requested for this address.\n\nRecovery code: {secret}\n"
        message.set_content(body)
        return message

    def _deliver_blocking(self, message: EmailMessage) -> DeliveryOutcome:
        try:
            with self._transport(self._host, self._port, timeout=self._timeout_seconds) as client:
                client.ehlo()
                if self._starttls and not self._use_ssl:
                    client.starttls()
                if self._username is not None:
                    client.login(self._username, self._password or "")
                client.send_message(message)
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPNotSupportedError,
        ):
            return DeliveryOutcome.FAILED
        except TimeoutError:
            return DeliveryOutcome.UNKNOWN
        except smtplib.SMTPConnectError as exc:
            raise RecoveryDeliveryRetryable("smtp connection failed before transmission") from exc
        except smtplib.SMTPException:
            return DeliveryOutcome.UNKNOWN
        except OSError as exc:
            raise RecoveryDeliveryRetryable("smtp connection failed before transmission") from exc
        return DeliveryOutcome.DELIVERED
