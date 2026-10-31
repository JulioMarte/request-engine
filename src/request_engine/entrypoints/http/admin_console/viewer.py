"""Display hints about who is signed in, learned from reads the console already made.

These hints only shape navigation (which sections are offered). They are never
authority: every page and action is still decided by the owner API, which may
deny what a hint offers. Hints are kept in process memory, keyed by a digest of
the upstream session (never the bearer itself), bounded and short-lived. A
restart or a second replica simply starts without hints and shows the neutral
navigation until the next home/organization read.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace

from request_engine.entrypoints.http.admin_console.session import AdminSession

_TENANT_PATH = re.compile(r"^/tenants/([0-9a-fA-F-]{36})(?:/|$)")
_TTL_SECONDS = 900
_MAX_ENTRIES = 512


@dataclass(frozen=True)
class OrganizationHint:
    organization_id: str
    display_name: str


@dataclass(frozen=True)
class ViewerHints:
    platform_access: bool | None = None
    organizations: tuple[OrganizationHint, ...] | None = None


class ViewerHintCache:
    def __init__(self, *, ttl_seconds: int = _TTL_SECONDS, max_entries: int = _MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: OrderedDict[str, tuple[float, ViewerHints]] = OrderedDict()

    @staticmethod
    def _key(session: AdminSession) -> str:
        return hashlib.sha256(session.access_token.encode("utf-8")).hexdigest()

    def get(self, session: AdminSession | None) -> ViewerHints:
        if session is None:
            return ViewerHints()
        key = self._key(session)
        entry = self._entries.get(key)
        if entry is None or entry[0] < time.monotonic():
            self._entries.pop(key, None)
            return ViewerHints()
        return entry[1]

    def _put(self, session: AdminSession, hints: ViewerHints) -> None:
        key = self._key(session)
        self._entries[key] = (time.monotonic() + self._ttl, hints)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def record_platform_access(self, session: AdminSession, allowed: bool) -> None:
        self._put(session, replace(self.get(session), platform_access=allowed))

    def record_organizations(
        self, session: AdminSession, organizations: tuple[OrganizationHint, ...]
    ) -> None:
        self._put(session, replace(self.get(session), organizations=organizations))

    def forget(self, session: AdminSession | None) -> None:
        if session is not None:
            self._entries.pop(self._key(session), None)


def tenant_from_path(path: str) -> str | None:
    match = _TENANT_PATH.match(path)
    return match.group(1).lower() if match else None


def navigation_context(path: str, hints: ViewerHints) -> dict[str, object]:
    """Template inputs for the role-aware rail; display only."""

    organizations = hints.organizations or ()
    current = tenant_from_path(path)
    if current is None and len(organizations) == 1:
        current = organizations[0].organization_id
    current_name = next(
        (item.display_name for item in organizations if item.organization_id == current), None
    )
    return {
        "nav_platform": hints.platform_access is not False,
        "nav_business_only": hints.platform_access is False,
        "nav_organization_id": current,
        "nav_organization_name": current_name,
        "nav_organization_count": len(organizations),
    }


__all__ = [
    "OrganizationHint",
    "ViewerHintCache",
    "ViewerHints",
    "navigation_context",
    "tenant_from_path",
]
