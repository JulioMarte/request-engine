from dataclasses import dataclass, replace
from uuid import UUID

from request_engine.platform.security.context import ActorContext

from .http_isolation_probe_flows import foreign_request as _flow_request
from .http_surface import PublicHttpOperation
from .tenant_sandbox import TenantSandbox, actor_for

ISOLATION_ACTOR_GRANTS = frozenset(
    {
        "appointments.record_arrival_estimate",
        "parties.register",
        "parties.add_contact_point",
        "parties.confirm_contact_point",
        "parties.rename",
        "parties.add_document",
        "parties.deactivate_contact_point",
        "parties.deactivate",
        "parties.lookup",
        "parties.read_revisions",
        "parties.rollback_identity",
        "parties.add_administrative_identifier",
        "parties.lookup_administrative_identifier",
        "staff.manage_own_admin_contact",
        "staff.confirm_own_admin_contact",
    }
)


@dataclass(frozen=True, slots=True)
class ForeignObjects:
    reservation_id: UUID
    reservation_revision: int
    queue_entry_id: UUID
    queue_entry_revision: int
    waitlist_entry_id: UUID
    waitlist_revision: int
    request_id: UUID
    request_revision: int
    reminder_plan_id: UUID
    reminder_revision: int
    actor_option_id: str


def isolation_actor(sandbox: TenantSandbox, *, allow_overrides: bool = True) -> ActorContext:
    base = actor_for(sandbox, allow_overrides=allow_overrides)
    return replace(base, capabilities=base.capabilities | ISOLATION_ACTOR_GRANTS)


def foreign_request(
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    name = operation.name
    if name == "capabilities.list":
        return "/v1/capabilities", {}, None, 200
    if name == "business.read":
        return "/v1/business", {}, None, 200
    if name == "catalog.offerings.list":
        return "/v1/catalog/offerings", {}, None, 200
    if name == "catalog.offerings.read":
        return f"/v1/catalog/offerings/{foreign.offering_key}", {}, None, 404
    if name == "appointments.find_slots":
        return (
            "/v1/appointments/slots",
            {
                "offering_version_id": str(foreign.offering_version_id),
                "window_start": "2030-01-07T13:00:00+00:00",
                "window_end": "2030-01-07T16:00:00+00:00",
            },
            None,
            404,
        )
    if name == "appointments.book":
        return (
            "/v1/appointments",
            {},
            {"option_id": objects.actor_option_id, "subject_party_id": str(foreign.party_id)},
            422,
        )
    if name == "appointments.read":
        return f"/v1/appointments/{objects.reservation_id}", {}, None, 404
    if name == "appointments.cancel":
        return (
            f"/v1/appointments/{objects.reservation_id}/cancel",
            {},
            {"expected_revision": objects.reservation_revision, "reason": "cross tenant"},
            404,
        )
    if name == "appointments.reschedule":
        return (
            f"/v1/appointments/{objects.reservation_id}/reschedule",
            {},
            {
                "option_id": objects.actor_option_id,
                "expected_revision": objects.reservation_revision,
            },
            404,
        )
    if name == "appointments.attendance":
        return (
            f"/v1/appointments/{objects.reservation_id}/attendance",
            {},
            {"response": "accepted", "expected_revision": objects.reservation_revision},
            404,
        )
    if name == "appointments.arrival_estimate":
        return (
            f"/v1/appointments/{objects.reservation_id}/arrival-estimate",
            {},
            {
                "estimated_arrival_at": "2030-01-07T15:45:00+00:00",
                "expected_revision": objects.reservation_revision,
            },
            404,
        )
    return _flow_request(operation, actor, foreign, objects)
