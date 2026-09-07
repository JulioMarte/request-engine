from uuid import uuid4

import pytest

from request_engine.platform.security.http import CapabilityRequired
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import require_platform_capability

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_platform_actor_has_no_tenant_scope_and_accepts_only_platform_authority() -> None:
    actor = PlatformActorContext(
        principal_id=uuid4(),
        authority_revision=4,
        capabilities=frozenset({"organization.provision", "platform.principal.provision"}),
    )

    assert not hasattr(actor, "organization_id")
    assert actor.allows("organization.provision")
    assert not actor.allows("staff.manage_authority")


@pytest.mark.parametrize(
    "capability",
    ["staff.manage_authority", "appointments.book", "platform.acting_for_operator"],
)
def test_platform_actor_rejects_non_platform_authority(capability: str) -> None:
    with pytest.raises(ValueError, match="non-platform capability"):
        PlatformActorContext(
            principal_id=uuid4(),
            authority_revision=1,
            capabilities=frozenset({capability}),
        )


def test_platform_actor_rejects_unknown_or_stale_authority_shape() -> None:
    with pytest.raises(ValueError, match="unknown platform capability"):
        PlatformActorContext(
            principal_id=uuid4(),
            authority_revision=1,
            capabilities=frozenset({"platform.future_root"}),
        )
    with pytest.raises(ValueError, match="authority_revision"):
        PlatformActorContext(
            principal_id=uuid4(),
            authority_revision=0,
            capabilities=frozenset(),
        )


def test_platform_capability_guard_cannot_use_tenant_or_operational_keys() -> None:
    actor = PlatformActorContext(
        principal_id=uuid4(),
        authority_revision=2,
        capabilities=frozenset({"organization.provision"}),
    )

    require_platform_capability(actor, "organization.provision")
    with pytest.raises(CapabilityRequired):
        require_platform_capability(actor, "appointments.book")
