from datetime import UTC, datetime
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.onboarding import BookingOnboardingSupply
from request_engine.modules.catalog.contracts.onboarding import CatalogOnboardingSupply
from request_engine.modules.communications.contracts.onboarding import (
    CommunicationsOnboardingSupply,
)
from request_engine.modules.onboarding.api.router import project_readiness
from request_engine.modules.onboarding.application.readiness import (
    OnboardingReadiness,
    OwnerBackedOnboardingReadiness,
)
from request_engine.modules.queue.contracts.onboarding import QueueOnboardingSupply
from request_engine.modules.tenancy.contracts.onboarding_readiness import (
    IdentityReadinessFacts,
    OnboardingIdentityFacts,
    RecoveryReadinessFacts,
    StaffAdministrationReadinessFacts,
    TenantControlReadinessFacts,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_VERIFIED_OPERATION_IDS = frozenset(
    {
        "staff_invite",
        "staff_manage_membership",
        "staff_manage_authority",
        "controller_policy_upgrade",
    }
)

_OBSERVED_AT = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _identity_facts(
    *,
    active_controller: bool = True,
    authenticatable_controller: bool = True,
    current_policy_ready: bool = True,
    recorded_policy_key: str | None = "tenant-controller-v3",
    staff_administration_available: bool = True,
) -> OnboardingIdentityFacts:
    return OnboardingIdentityFacts(
        identity=IdentityReadinessFacts(
            active_controller=active_controller,
            authenticatable_controller=authenticatable_controller,
        ),
        tenant_control=TenantControlReadinessFacts(
            current_policy_ready=current_policy_ready,
            recorded_policy_key=recorded_policy_key,
        ),
        staff_administration=StaffAdministrationReadinessFacts(
            available=staff_administration_available,
        ),
        recovery=RecoveryReadinessFacts(known=False, ready=None),
        observed_at=_OBSERVED_AT,
        controller_authority_revision=7,
        policy_revision=3,
    )


def _readiness(
    *,
    identity_facts: OnboardingIdentityFacts | None,
    has_business_party: bool = True,
    location_count: int = 1,
    bookable_offering_version_count: int = 1,
    resource_supply_count: int = 1,
    active_queue_count: int = 1,
    disabled_purpose_count: int = 0,
) -> OnboardingReadiness:
    return OnboardingReadiness(
        has_business_party=has_business_party,
        location_count=location_count,
        bookable_offering_version_count=bookable_offering_version_count,
        resource_supply_count=resource_supply_count,
        active_queue_count=active_queue_count,
        disabled_purpose_count=disabled_purpose_count,
        identity_facts=identity_facts,
    )


def test_missing_owner_facts_project_actionable_capability_guidance() -> None:
    view = project_readiness(
        _readiness(
            identity_facts=None,
            has_business_party=False,
            location_count=0,
            bookable_offering_version_count=0,
            resource_supply_count=0,
            active_queue_count=0,
            disabled_purpose_count=2,
        )
    )

    assert view.business_party.blockers[0].model_dump() == {
        "code": "business_party_missing",
        "owner": "tenancy",
        "resolution_capabilities": (),
        "requires_operator": False,
        "operation_id": None,
    }
    assert view.locations.blockers[0].model_dump() == {
        "code": "location_missing",
        "owner": "catalog",
        "resolution_capabilities": ("catalog.manage",),
        "requires_operator": False,
        "operation_id": None,
    }
    assert [blocker.model_dump() for blocker in view.appointments.blockers] == [
        {
            "code": "no_bookable_offering",
            "owner": "catalog",
            "resolution_capabilities": ("catalog.manage",),
            "requires_operator": False,
            "operation_id": None,
        },
        {
            "code": "no_resource_supply",
            "owner": "booking",
            "resolution_capabilities": ("booking.manage_supply",),
            "requires_operator": False,
            "operation_id": None,
        },
    ]
    assert view.walk_in_queue.blockers[0].model_dump() == {
        "code": "service_queue_missing",
        "owner": "queue",
        "resolution_capabilities": ("queue.configure",),
        "requires_operator": False,
        "operation_id": None,
    }
    assert view.communications.blockers[0].model_dump() == {
        "code": "channel_purpose_disabled",
        "owner": "communications",
        "resolution_capabilities": ("communications.configure",),
        "requires_operator": False,
        "operation_id": None,
    }


def test_ready_owner_facts_have_no_synthetic_actions() -> None:
    view = project_readiness(_readiness(identity_facts=_identity_facts()))

    for section in (
        view.business_party,
        view.locations,
        view.appointments,
        view.walk_in_queue,
        view.communications,
        view.identity,
        view.tenant_control,
        view.staff_administration,
    ):
        assert section.status == "ready"
        assert section.ready
        assert section.blockers == ()
    assert view.recovery.status == "unknown"
    assert view.recovery.ready is False
    assert view.observed_at == _OBSERVED_AT
    assert view.controller_authority_revision == 7
    assert view.policy_revision == 3


def test_onboarding_guidance_uses_only_verified_operation_ids() -> None:
    view = project_readiness(
        _readiness(
            identity_facts=_identity_facts(
                active_controller=False,
                authenticatable_controller=False,
                current_policy_ready=False,
                recorded_policy_key=None,
                staff_administration_available=False,
            ),
            location_count=0,
            bookable_offering_version_count=0,
            resource_supply_count=0,
            active_queue_count=0,
            disabled_purpose_count=1,
        )
    )

    found = {
        blocker.operation_id
        for section in (
            view.business_party,
            view.locations,
            view.appointments,
            view.walk_in_queue,
            view.communications,
            view.identity,
            view.tenant_control,
            view.staff_administration,
            view.recovery,
        )
        for blocker in section.blockers
        if blocker.operation_id is not None
    }
    assert found
    assert found <= _VERIFIED_OPERATION_IDS


def test_unknown_identity_facts_are_never_ready() -> None:
    view = project_readiness(_readiness(identity_facts=None))

    for section in (
        view.identity,
        view.tenant_control,
        view.staff_administration,
        view.recovery,
    ):
        assert section.status == "unknown"
        assert section.ready is False
        assert section.blockers == ()
    assert view.observed_at is None
    assert view.controller_authority_revision is None
    assert view.policy_revision is None


def test_unconfigured_oidc_does_not_block_the_native_path() -> None:
    view = project_readiness(
        _readiness(identity_facts=_identity_facts(authenticatable_controller=True))
    )

    assert view.identity.status == "ready"
    assert view.identity.blockers == ()
    assert "oidc" not in str(view.model_dump()).lower()


def test_distinct_journeys_do_not_block_on_unused_features() -> None:
    view = project_readiness(_readiness(identity_facts=_identity_facts(), active_queue_count=0))

    assert view.appointments.status == "ready"
    assert view.appointments.blockers == ()
    assert [blocker.code for blocker in view.walk_in_queue.blockers] == ["service_queue_missing"]


class _FailingIdentityReader:
    async def read_identity_facts(self, *, organization_id: UUID) -> OnboardingIdentityFacts:
        raise RuntimeError("identity facts reader unavailable")


class _StaticPartyReader:
    async def has_active_organization_party(self, *, organization_id: UUID) -> bool:
        return True


class _StaticCatalogReader:
    async def read_catalog_supply(self, *, organization_id: UUID) -> CatalogOnboardingSupply:
        return CatalogOnboardingSupply(location_count=1, bookable_offering_version_count=1)


class _StaticBookingReader:
    async def read_booking_supply(self, *, organization_id: UUID) -> BookingOnboardingSupply:
        return BookingOnboardingSupply(resource_supply_count=1)


class _StaticQueueReader:
    async def read_queue_supply(self, *, organization_id: UUID) -> QueueOnboardingSupply:
        return QueueOnboardingSupply(active_queue_count=1)


class _StaticCommunicationsReader:
    async def read_communications_supply(
        self, *, organization_id: UUID
    ) -> CommunicationsOnboardingSupply:
        return CommunicationsOnboardingSupply(disabled_purpose_count=0)


@pytest.mark.asyncio
async def test_reader_failure_yields_unknown_identity_not_ready() -> None:
    reader = OwnerBackedOnboardingReadiness(
        party_reader=_StaticPartyReader(),
        catalog_reader=_StaticCatalogReader(),
        booking_reader=_StaticBookingReader(),
        queue_reader=_StaticQueueReader(),
        communications_reader=_StaticCommunicationsReader(),
        identity_reader=_FailingIdentityReader(),
    )

    facts = await reader.read(organization_id=UUID(int=0))
    assert facts.identity_facts is None

    view = project_readiness(facts)
    assert view.identity.status == "unknown"
    assert view.identity.ready is False
    assert view.identity.blockers == ()
    assert view.tenant_control.status == "unknown"
    assert view.staff_administration.status == "unknown"
