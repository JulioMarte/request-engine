from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.freshness import (
    ReauthenticationRequired,
    enforce_step_up,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

NOW = datetime(2026, 9, 16, tzinfo=UTC)


def _actor(*, authenticated_at: datetime | None) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
        authenticated_at=authenticated_at,
    )


def test_identity_link_self_declares_recent_authentication() -> None:
    definition = capability_definition("identity.link_self")
    assert definition is not None
    assert definition.requires_recent_authentication is True


def test_capability_without_the_flag_is_not_gated() -> None:
    definition = capability_definition("staff.read")
    assert definition is not None
    assert definition.requires_recent_authentication is False

    enforce_step_up(_actor(authenticated_at=None), "staff.read", now=NOW)


def test_gated_capability_rejects_absent_and_stale_authentication() -> None:
    with pytest.raises(ReauthenticationRequired):
        enforce_step_up(_actor(authenticated_at=None), "identity.link_self", now=NOW)
    with pytest.raises(ReauthenticationRequired):
        enforce_step_up(
            _actor(authenticated_at=NOW - timedelta(minutes=10)),
            "identity.link_self",
            now=NOW,
        )


def test_gated_capability_accepts_recent_authentication() -> None:
    enforce_step_up(
        _actor(authenticated_at=NOW - timedelta(minutes=1)),
        "identity.link_self",
        now=NOW,
    )
