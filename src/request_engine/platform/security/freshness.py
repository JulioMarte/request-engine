from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from request_engine.platform.security.context import ActorContext

REAUTHENTICATION_WINDOW: Final[timedelta] = timedelta(minutes=5)


class ReauthenticationRequired(PermissionError):
    """Raised when an operation needs a more recent credential proof."""


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
