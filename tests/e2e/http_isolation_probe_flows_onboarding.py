from __future__ import annotations

from typing import TYPE_CHECKING

from .http_surface import PublicHttpOperation

if TYPE_CHECKING:
    from .http_isolation_probes import ForeignObjects
    from .tenant_sandbox import TenantSandbox


def foreign_request(
    operation: PublicHttpOperation,
    actor: TenantSandbox,
    foreign: TenantSandbox,
    objects: ForeignObjects,
) -> tuple[str, dict[str, str], dict[str, object] | None, int]:
    del objects
    name = operation.name
    if name == "organization.bootstrap":
        return (
            "/v1/organization/bootstrap-operational-authority",
            {},
            {"authority_party_id": str(foreign.party_id)},
            404,
        )
    if name == "catalog.manage.resource_capability":
        return (
            "/v1/catalog/resource-capabilities",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "capability_key": "probe-capability",
                "display_name": "Probe capability",
            },
            403,
        )
    if name == "catalog.manage.offering":
        return (
            "/v1/catalog/offerings",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "offering_key": "probe-offering",
                "display_name": "Probe offering",
                "duration_minutes": 30,
            },
            403,
        )
    if name == "catalog.manage.offering_booking_policy":
        return (
            f"/v1/catalog/offerings/{foreign.offering_version_id}/booking-policy",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "expected_revision": 0,
                "booking_policy": {
                    "slot_step_minutes": 30,
                    "attendance": {"confirmation_required": False},
                    "communications": {"confirmation": False},
                    "slot_recovery": {"enabled": False},
                },
            },
            403,
        )
    if name == "booking.manage_supply":
        return (
            "/v1/booking/resources",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "location_id": str(foreign.location_id),
                "resource_key": "probe-resource",
                "display_name": "Probe resource",
            },
            403,
        )
    if name == "queue.configure":
        return (
            "/v1/queues",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "location_id": str(foreign.location_id),
                "queue_key": "probe-queue",
                "display_name": "Probe queue",
            },
            403,
        )
    if name == "communications.configure_channel_policy":
        return (
            "/v1/communications/channel-policies/appointment_confirmation",
            {},
            {
                "authority_party_id": str(foreign.party_id),
                "enabled": True,
                "channels": ["whatsapp", "sms", "email"],
                "expected_revision": 0,
            },
            403,
        )
    if name == "onboarding.readiness":
        return "/v1/onboarding/readiness", {}, None, 200
    raise AssertionError(f"missing onboarding tenant probe for {name}")
