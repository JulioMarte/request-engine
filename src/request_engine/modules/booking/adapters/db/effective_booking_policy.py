"""Effective OfferingVersion booking-policy selection for booking reads.

`request_engine.offering_version_booking_policies` is catalog's append-only
override ledger. The bootstrap policy in `offering_versions.booking_policy`
stays in force until the first override revision is appended.
"""

EFFECTIVE_BOOKING_POLICY_SELECT = """
COALESCE(
    (
        SELECT pol.booking_policy
        FROM request_engine.offering_version_booking_policies pol
        WHERE pol.organization_id = ov.organization_id
          AND pol.offering_version_id = ov.id
        ORDER BY pol.revision DESC
        LIMIT 1
    ),
    ov.booking_policy
) AS booking_policy
"""
