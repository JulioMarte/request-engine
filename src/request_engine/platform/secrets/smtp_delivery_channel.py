"""SMTP delivery channel for governed identity recovery secrets.

The channel is a projection of the technical delivery boundary: the raw proof
is placed only in the message body and the outcome distinguishes a definitive
provider rejection from a connection failure that never transmitted anything
and from an ambiguous post-connect failure that must not be retried blindly.
"""

import asyncio
import hashlib
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import getaddresses
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)

_SUBJECT = "Request Engine identity recovery"
_VERIFICATION_SUBJECT = "Verify your Request Engine recovery address"


def _validate_destination(value: str) -> None:
    # send_message derives its envelope from To. Never let a single destination
    # expand into a recipient list, display-name/group syntax or header injection.
    addresses = getaddresses([value])
    if (
        not value.isascii()
        or any(character in value for character in "\r\n")
        or "@" not in value
        or len(addresses) != 1
        or addresses[0] != ("", value)
    ):
        raise RecoveryDeliveryPermanent("delivery destination must be one ASCII mailbox")


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
        purpose: Literal["identity_recovery", "staff_invitation"] = "identity_recovery",
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
        if purpose == "staff_invitation" and not reset_url:
            raise ValueError("staff invitation acceptance URL is required")
        self._purpose = purpose
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
        _validate_destination(destination_reference)
        message = self._build_message(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )
        return await asyncio.to_thread(self._deliver_blocking, message)

    async def send_recovery(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        return await self.send(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        _validate_destination(destination_reference)
        message = self._build_verification_message(
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
        message["Subject"] = (
            "You are invited to Request Engine" if self._purpose == "staff_invitation" else _SUBJECT
        )
        message_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<{message_id}@request-engine>"
        if self._purpose == "staff_invitation":
            invitation_id, separator, proof = secret.partition(".")
            try:
                UUID(invitation_id)
            except ValueError as exc:
                raise RecoveryDeliveryPermanent("invalid invitation proof envelope") from exc
            if not separator or not proof:
                raise RecoveryDeliveryPermanent("invalid invitation proof envelope")
            assert self._reset_url is not None
            link = (
                f"{self._reset_url.rstrip('/')}/{invitation_id}/accept"
                f"#token={quote(secret, safe='')}"
            )
            body = (
                "You have been invited to join an organization in Request Engine.\n\n"
                f"Sign in or create your identity, then accept here:\n{link}\n\n"
                "Acceptance creates a membership, not permission to administer the organization.\n"
                "If you did not expect this invitation, ignore this message.\n"
            )
        elif self._reset_url is not None:
            link = f"{self._reset_url}#token={quote(secret, safe='')}"
            body = (
                "A recovery proof was requested for this address.\n\n"
                f"Open the following link to continue:\n{link}\n"
            )
        else:
            body = f"A recovery proof was requested for this address.\n\nRecovery code: {secret}\n"
        message.set_content(body)
        return message

    def _build_verification_message(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = destination_reference
        message["Subject"] = _VERIFICATION_SUBJECT
        message_id = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<{message_id}@request-engine>"
        message.set_content(
            "A recovery address was added to a Request Engine identity.\n\n"
            f"Verification code: {secret}\n\n"
            "If you did not request this, do not share or use this code.\n"
        )
        return message

    def _deliver_blocking(self, message: EmailMessage) -> DeliveryOutcome:
        transmission_started = False
        try:
            # smtplib's built-in defaults for SMTP_SSL/starttls do not verify the
            # server certificate or hostname; always pass a verifying context so
            # a recovery proof cannot be leaked to an on-path impersonator.
            if self._use_ssl:
                client = self._transport(
                    self._host,
                    self._port,
                    timeout=self._timeout_seconds,
                    context=ssl.create_default_context(),
                )
            else:
                client = self._transport(self._host, self._port, timeout=self._timeout_seconds)
            with client:
                client.ehlo()
                if self._starttls and not self._use_ssl:
                    client.starttls(context=ssl.create_default_context())
                if self._username is not None:
                    client.login(self._username, self._password or "")
                transmission_started = True
                client.send_message(message)
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPAuthenticationError,
            smtplib.SMTPNotSupportedError,
            ssl.SSLCertVerificationError,
        ):
            return DeliveryOutcome.FAILED
        except TimeoutError:
            return DeliveryOutcome.UNKNOWN
        except smtplib.SMTPConnectError as exc:
            raise RecoveryDeliveryRetryable("smtp connection failed before transmission") from exc
        except smtplib.SMTPException:
            return DeliveryOutcome.UNKNOWN
        except OSError as exc:
            if transmission_started:
                return DeliveryOutcome.UNKNOWN
            raise RecoveryDeliveryRetryable("smtp connection failed before transmission") from exc
        return DeliveryOutcome.DELIVERED
