from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.freshness import (
    PhishingResistantAuthenticationRequired,
    RecentAuthenticationRequired,
    RecoveryCompletionRequired,
    recovery_safe_capabilities,
    require_phishing_resistant_authentication,
    require_recent_authentication,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def _actor(
    *,
    authenticated_at: datetime | None,
    assurance: AuthenticationAssurance | None,
    user_verified: bool = False,
    recovery_derived: bool = False,
    recovery_restricted: bool = False,
) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(),
        authenticated_at=authenticated_at,
        authentication_assurance=assurance,
        user_verified=user_verified,
        recovery_derived=recovery_derived,
        recovery_restricted=recovery_restricted,
    )


def test_recent_phishing_resistant_authentication_is_accepted() -> None:
    require_phishing_resistant_authentication(
        _actor(
            authenticated_at=NOW - timedelta(minutes=1),
            assurance=AuthenticationAssurance.PHISHING_RESISTANT,
            user_verified=True,
        ),
        now=NOW,
    )


@pytest.mark.parametrize(
    "assurance,user_verified,recovery_derived",
    [
        (AuthenticationAssurance.SINGLE_FACTOR, False, False),
        (AuthenticationAssurance.MFA, False, False),
        (AuthenticationAssurance.PHISHING_RESISTANT, False, False),
        (AuthenticationAssurance.PHISHING_RESISTANT, True, True),
        (None, False, False),
    ],
)
def test_insufficient_assurance_reports_phishing_resistant_required(
    assurance: AuthenticationAssurance | None,
    user_verified: bool,
    recovery_derived: bool,
) -> None:
    with pytest.raises(PhishingResistantAuthenticationRequired):
        require_phishing_resistant_authentication(
            _actor(
                authenticated_at=NOW - timedelta(minutes=1),
                assurance=assurance,
                user_verified=user_verified,
                recovery_derived=recovery_derived,
            ),
            now=NOW,
        )


def test_stale_strong_authentication_reports_recent_authentication_required() -> None:
    with pytest.raises(RecentAuthenticationRequired):
        require_phishing_resistant_authentication(
            _actor(
                authenticated_at=NOW - timedelta(minutes=10),
                assurance=AuthenticationAssurance.PHISHING_RESISTANT,
                user_verified=True,
            ),
            now=NOW,
        )


def test_absent_strong_authentication_time_reports_recent_authentication_required() -> None:
    with pytest.raises(RecentAuthenticationRequired):
        require_phishing_resistant_authentication(
            _actor(
                authenticated_at=None,
                assurance=AuthenticationAssurance.PHISHING_RESISTANT,
                user_verified=True,
            ),
            now=NOW,
        )


def test_recovery_restricted_actor_cannot_use_sensitive_authority() -> None:
    with pytest.raises(RecoveryCompletionRequired):
        require_phishing_resistant_authentication(
            _actor(
                authenticated_at=NOW - timedelta(minutes=1),
                assurance=AuthenticationAssurance.PHISHING_RESISTANT,
                user_verified=True,
                recovery_restricted=True,
            ),
            now=NOW,
        )


def test_recovery_restricted_actor_cannot_use_generic_recent_authentication_gate() -> None:
    with pytest.raises(RecoveryCompletionRequired):
        require_recent_authentication(
            _actor(
                authenticated_at=NOW - timedelta(minutes=1),
                assurance=AuthenticationAssurance.SINGLE_FACTOR,
                recovery_restricted=True,
            ),
            now=NOW,
        )


def test_recovery_posture_filters_authority_changes_without_mutating_other_capabilities() -> None:
    standing = frozenset(
        {
            "staff.invite",
            "platform.owner.provision",
            "appointments.book",
            "business.get_info",
        }
    )

    effective = recovery_safe_capabilities(standing, recovery_restricted=True)

    assert standing == frozenset(
        {
            "staff.invite",
            "platform.owner.provision",
            "appointments.book",
            "business.get_info",
        }
    )
    assert "staff.invite" not in effective
    assert "platform.owner.provision" not in effective
    assert "appointments.book" in effective
    assert "business.get_info" in effective


def test_normal_posture_preserves_standing_capabilities_exactly() -> None:
    standing = frozenset({"staff.invite", "appointments.book"})

    assert (
        recovery_safe_capabilities(
            standing,
            recovery_restricted=False,
        )
        is standing
    )
