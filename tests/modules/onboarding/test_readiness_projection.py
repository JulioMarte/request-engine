from request_engine.modules.onboarding.api.router import project_readiness
from request_engine.modules.onboarding.application.readiness import OnboardingReadiness


def test_missing_owner_facts_project_actionable_capability_guidance() -> None:
    view = project_readiness(
        OnboardingReadiness(
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
    }
    assert view.locations.blockers[0].model_dump() == {
        "code": "location_missing",
        "owner": "catalog",
        "resolution_capabilities": ("catalog.manage",),
    }
    assert [blocker.model_dump() for blocker in view.appointments.blockers] == [
        {
            "code": "no_bookable_offering",
            "owner": "catalog",
            "resolution_capabilities": ("catalog.manage",),
        },
        {
            "code": "no_resource_supply",
            "owner": "booking",
            "resolution_capabilities": ("booking.manage_supply",),
        },
    ]
    assert view.walk_in_queue.blockers[0].model_dump() == {
        "code": "service_queue_missing",
        "owner": "queue",
        "resolution_capabilities": ("queue.configure",),
    }
    assert view.communications.blockers[0].model_dump() == {
        "code": "channel_purpose_disabled",
        "owner": "communications",
        "resolution_capabilities": ("communications.configure",),
    }


def test_ready_owner_facts_have_no_synthetic_actions() -> None:
    view = project_readiness(
        OnboardingReadiness(
            has_business_party=True,
            location_count=1,
            bookable_offering_version_count=1,
            resource_supply_count=1,
            active_queue_count=1,
            disabled_purpose_count=0,
        )
    )

    for section in (
        view.business_party,
        view.locations,
        view.appointments,
        view.walk_in_queue,
        view.communications,
    ):
        assert section.ready
        assert section.blockers == ()


def test_onboarding_guidance_does_not_invent_operation_ids() -> None:
    view = project_readiness(
        OnboardingReadiness(
            has_business_party=True,
            location_count=0,
            bookable_offering_version_count=0,
            resource_supply_count=0,
            active_queue_count=0,
            disabled_purpose_count=1,
        )
    )

    payload = view.model_dump()
    assert "operation_id" not in str(payload)
    assert "suggested_operation" not in str(payload)
