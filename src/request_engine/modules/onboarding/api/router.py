from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from request_engine.modules.onboarding.application.readiness import (
    OnboardingReadiness,
    OnboardingReadinessReader,
)
from request_engine.modules.tenancy.contracts.onboarding_readiness import OnboardingIdentityFacts
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

ReadinessStatus = Literal["ready", "blocked", "unknown"]


class ReadinessBlockerView(BaseModel):
    """Machine-readable setup blocker without transport-coupling Onboarding to another owner."""

    model_config = ConfigDict(extra="forbid")

    code: str
    owner: str
    resolution_capabilities: tuple[str, ...] = ()
    requires_operator: bool = False
    operation_id: str | None = None


class JourneyReadinessView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReadinessStatus
    ready: bool
    blockers: tuple[ReadinessBlockerView, ...] = ()


class CountedJourneyReadinessView(JourneyReadinessView):
    count: int


class OnboardingReadinessView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_party: JourneyReadinessView
    locations: CountedJourneyReadinessView
    appointments: JourneyReadinessView
    walk_in_queue: CountedJourneyReadinessView
    communications: JourneyReadinessView
    identity: JourneyReadinessView
    tenant_control: JourneyReadinessView
    staff_administration: JourneyReadinessView
    recovery: JourneyReadinessView
    observed_at: datetime | None = None
    controller_authority_revision: int | None = None
    policy_revision: int | None = None


def _blocker(
    code: str,
    owner: str,
    *resolution_capabilities: str,
    requires_operator: bool = False,
    operation_id: str | None = None,
) -> ReadinessBlockerView:
    return ReadinessBlockerView(
        code=code,
        owner=owner,
        resolution_capabilities=resolution_capabilities,
        requires_operator=requires_operator,
        operation_id=operation_id,
    )


def _section(
    ready: bool,
    blockers: tuple[ReadinessBlockerView, ...],
) -> JourneyReadinessView:
    return JourneyReadinessView(
        status="ready" if ready else "blocked",
        ready=ready,
        blockers=blockers,
    )


def _unknown_section() -> JourneyReadinessView:
    return JourneyReadinessView(status="unknown", ready=False, blockers=())


def _identity_section(facts: OnboardingIdentityFacts | None) -> JourneyReadinessView:
    if facts is None:
        return _unknown_section()
    if not facts.identity.active_controller:
        return _section(
            False,
            (
                _blocker(
                    "active_controller_missing",
                    "tenancy",
                    "staff.manage_membership",
                    "staff.manage_authority",
                    requires_operator=True,
                    operation_id="staff_manage_membership",
                ),
            ),
        )
    if not facts.identity.authenticatable_controller:
        return _section(
            False,
            (
                _blocker(
                    "authentication_path_missing",
                    "tenancy",
                    "staff.invite",
                    "identity.link_self",
                    operation_id="staff_invite",
                ),
            ),
        )
    return _section(True, ())


def _tenant_control_section(facts: OnboardingIdentityFacts | None) -> JourneyReadinessView:
    if facts is None:
        return _unknown_section()
    if not facts.tenant_control.current_policy_ready:
        return _section(
            False,
            (
                _blocker(
                    "controller_policy_upgrade_required",
                    "tenancy",
                    "controller_policy_upgrade",
                    requires_operator=True,
                    operation_id="controller_policy_upgrade",
                ),
            ),
        )
    return _section(True, ())


def _staff_administration_section(facts: OnboardingIdentityFacts | None) -> JourneyReadinessView:
    if facts is None:
        return _unknown_section()
    if not facts.staff_administration.available:
        return _section(
            False,
            (
                _blocker(
                    "staff_management_unavailable",
                    "tenancy",
                    "staff.manage_authority",
                    "staff.manage_membership",
                    requires_operator=True,
                    operation_id="staff_manage_authority",
                ),
            ),
        )
    return _section(True, ())


def _recovery_section(facts: OnboardingIdentityFacts | None) -> JourneyReadinessView:
    if facts is None or not facts.recovery.known:
        return _unknown_section()
    return _section(bool(facts.recovery.ready), ())


def project_readiness(facts: OnboardingReadiness) -> OnboardingReadinessView:
    """Project owner facts into actionable guidance without acquiring execution authority."""

    business_party_blockers = (
        () if facts.has_business_party else (_blocker("business_party_missing", "tenancy"),)
    )
    location_blockers = (
        ()
        if facts.location_count > 0
        else (_blocker("location_missing", "catalog", "catalog.manage"),)
    )

    appointment_blockers: list[ReadinessBlockerView] = []
    if facts.bookable_offering_version_count == 0:
        appointment_blockers.append(_blocker("no_bookable_offering", "catalog", "catalog.manage"))
    if facts.resource_supply_count == 0:
        appointment_blockers.append(
            _blocker("no_resource_supply", "booking", "booking.manage_supply")
        )

    queue_blockers = (
        ()
        if facts.active_queue_count > 0
        else (_blocker("service_queue_missing", "queue", "queue.configure"),)
    )
    communication_blockers = (
        ()
        if facts.disabled_purpose_count == 0
        else (
            _blocker(
                "channel_purpose_disabled",
                "communications",
                "communications.configure",
            ),
        )
    )

    identity_facts = facts.identity_facts
    return OnboardingReadinessView(
        business_party=_section(not business_party_blockers, business_party_blockers),
        locations=CountedJourneyReadinessView(
            status="ready" if not location_blockers else "blocked",
            ready=not location_blockers,
            count=facts.location_count,
            blockers=location_blockers,
        ),
        appointments=_section(not appointment_blockers, tuple(appointment_blockers)),
        walk_in_queue=CountedJourneyReadinessView(
            status="ready" if not queue_blockers else "blocked",
            ready=not queue_blockers,
            count=facts.active_queue_count,
            blockers=queue_blockers,
        ),
        communications=_section(not communication_blockers, communication_blockers),
        identity=_identity_section(identity_facts),
        tenant_control=_tenant_control_section(identity_facts),
        staff_administration=_staff_administration_section(identity_facts),
        recovery=_recovery_section(identity_facts),
        observed_at=identity_facts.observed_at if identity_facts is not None else None,
        controller_authority_revision=(
            identity_facts.controller_authority_revision if identity_facts is not None else None
        ),
        policy_revision=(identity_facts.policy_revision if identity_facts is not None else None),
    )


def create_onboarding_readiness_router(
    *,
    reader: OnboardingReadinessReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def readiness(
        current: Annotated[ActorContext, Depends(actor)],
        response: Response,
    ) -> OnboardingReadinessView:
        require_capability(current, "onboarding.read")
        facts = await reader.read(organization_id=current.organization_id)
        response.headers["Cache-Control"] = "no-store"
        return project_readiness(facts)

    add_capability_route(
        router,
        "/readiness",
        readiness,
        capability="onboarding.read",
        methods=["GET"],
        operation_id="onboarding_read",
        response_model=OnboardingReadinessView,
    )
    return router
