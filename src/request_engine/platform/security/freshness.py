from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.context import ActorContext

REAUTHENTICATION_WINDOW: Final[timedelta] = timedelta(minutes=5)


class ReauthenticationRequired(PermissionError):
    """Raised when an operation needs a more recent credential proof."""


class PhishingResistantAuthenticationRequired(PermissionError):
    """Raised when an operation needs a phishing-resistant HUMAN proof."""


class RecentAuthenticationRequired(PermissionError):
    """Raised when a strong proof exists but is older than the freshness window."""


def require_recent_authentication(
    actor: ActorContext,
    *,
    now: datetime,
    window: timedelta = REAUTHENTICATION_WINDOW,
) -> None:
    """Fail closed unless the actor proved its credential inside ``window``.

    ADR 0013 accepts a reauthentication proof of at most five minutes. An absent
    or timezone-naive ``authenticated_at`` is treated as stale.
    """

    authenticated_at = actor.authenticated_at
    if authenticated_at is None or authenticated_at.tzinfo is None:
        raise ReauthenticationRequired("recent reauthentication is required")
    if now - authenticated_at > window:
        raise ReauthenticationRequired("recent reauthentication is required")


def require_phishing_resistant_authentication(
    actor: ActorContext,
    *,
    now: datetime,
    window: timedelta = REAUTHENTICATION_WINDOW,
) -> None:
    """Fail closed unless the actor holds a recent phishing-resistant proof.

    This is the reusable guard for sensitive platform operations (owner/admin
    changes, secret rotation, provider activation). It distinguishes the two
    failure classes the plan requires:

    - insufficient assurance (including any recovery-derived session, which is
      never phishing-resistant) -> ``PhishingResistantAuthenticationRequired``;
    - sufficient assurance that is too old -> ``RecentAuthenticationRequired``.

    The evidence comes only from the trusted actor context, never from the
    request. It is not SMTP-, P7- or Platform-Owner-specific.
    """

    if actor.recovery_derived or (
        actor.authentication_assurance is not AuthenticationAssurance.PHISHING_RESISTANT
        or not actor.user_verified
    ):
        raise PhishingResistantAuthenticationRequired(
            "recent phishing-resistant authentication is required"
        )
    authenticated_at = actor.authenticated_at
    if authenticated_at is None or authenticated_at.tzinfo is None:
        raise RecentAuthenticationRequired("recent strong authentication is required")
    if now - authenticated_at > window:
        raise RecentAuthenticationRequired("recent strong authentication is required")


def enforce_step_up(
    actor: ActorContext,
    capability_key: str,
    *,
    now: datetime,
    window: timedelta = REAUTHENTICATION_WINDOW,
) -> None:
    """Apply registry-declared reauthentication freshness for one capability.

    Enforcement is driven by ``CapabilityDefinition.requires_recent_authentication``
    so a step-up operation cannot silently drift from its declared policy. A
    capability without the flag (or an unknown capability) is not gated here.
    """

    definition = capability_definition(capability_key)
    if definition is not None and definition.requires_recent_authentication:
        require_recent_authentication(actor, now=now, window=window)
