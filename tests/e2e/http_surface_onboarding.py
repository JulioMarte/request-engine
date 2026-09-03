from .http_surface import (
    PROBE_UUID,
    PROBE_UUID_2,
    HttpProbe,
    PublicHttpOperation,
    TenantIsolationMode,
)

ONBOARDING_HTTP_OPERATIONS: tuple[PublicHttpOperation, ...] = (
    PublicHttpOperation(
        "organization.bootstrap",
        "POST",
        "/v1/organization/bootstrap-operational-authority",
        "organization.bootstrap",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/organization/bootstrap-operational-authority",
            body={"authority_party_id": PROBE_UUID},
        ),
    ),
    PublicHttpOperation(
        "catalog.manage.resource_capability",
        "POST",
        "/v1/catalog/resource-capabilities",
        "catalog.manage",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/catalog/resource-capabilities",
            body={
                "authority_party_id": PROBE_UUID,
                "capability_key": "probe-capability",
                "display_name": "Probe capability",
            },
        ),
    ),
    PublicHttpOperation(
        "catalog.manage.offering",
        "POST",
        "/v1/catalog/offerings",
        "catalog.manage",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/catalog/offerings",
            body={
                "authority_party_id": PROBE_UUID,
                "offering_key": "probe-offering",
                "display_name": "Probe offering",
                "duration_minutes": 30,
            },
        ),
    ),
    PublicHttpOperation(
        "catalog.manage.offering_booking_policy",
        "PUT",
        "/v1/catalog/offerings/{offering_version_id}/booking-policy",
        "catalog.manage",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            f"/v1/catalog/offerings/{PROBE_UUID}/booking-policy",
            body={
                "authority_party_id": PROBE_UUID,
                "expected_revision": 0,
                "booking_policy": {
                    "slot_step_minutes": 30,
                    "attendance": {"confirmation_required": False},
                    "communications": {"confirmation": False},
                    "slot_recovery": {"enabled": False},
                },
            },
        ),
    ),
    PublicHttpOperation(
        "booking.manage_supply",
        "POST",
        "/v1/booking/resources",
        "booking.manage_supply",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/booking/resources",
            body={
                "authority_party_id": PROBE_UUID,
                "location_id": PROBE_UUID_2,
                "resource_key": "probe-resource",
                "display_name": "Probe resource",
            },
        ),
    ),
    PublicHttpOperation(
        "queue.configure",
        "POST",
        "/v1/queues",
        "queue.configure",
        True,
        True,
        TenantIsolationMode.CONTEXTUAL,
        HttpProbe(
            "/v1/queues",
            body={
                "authority_party_id": PROBE_UUID,
                "location_id": PROBE_UUID_2,
                "queue_key": "probe-queue",
                "display_name": "Probe queue",
            },
        ),
    ),
)
