# Catalog module

> **V3 baseline module.**

Owns structured operational configuration that describes **what the business offers** and the stable vocabulary needed to plan local bookings:

```text
Location
Offering
OfferingVersion
ResourceCapability
OfferingResourceRequirement
structured business-profile/public-hours configuration where authoritative
```

`OfferingVersion` becomes immutable once referenced by authoritative state. Appointment-relevant configuration such as duration, bookable locations, resource requirements and policy/version references belongs to the exact version used by booking.

A baseline `OfferingResourceRequirement` is deliberately simple:

```text
one mandatory requirement
→ one ResourceCapability
→ one concrete Resource selected by booking
→ quantity units consumed for the appointment interval
```

Multiple requirement rows are ANDed. V3 baseline does not support OR/k-of-n requirement expressions, reusable requirement-template graphs, capacity pools or late binding optimizers.

### Decision: no `ResourceRequirementTemplate` baseline

The earlier reusable-template abstraction is unnecessary for the first verticals. Requirements are immutable children/configuration of an `OfferingVersion`. Extract a reusable template later only if multiple OfferingVersions demonstrably share an independently managed requirement definition.

Booking owns concrete `Resource`, availability, capacity claims/holds and Reservations. Catalog never owns runtime capacity commitment state.

Expected queries include:

```text
GetBusinessInfo
SearchOfferings
GetOfferingDetails
GetLocations
```

## Onboarding and bootstrap surfaces (docs/v3/44)

Catalog exposes its owner commands for empty-tenant onboarding without a new
authority owner:

- `POST /v1/catalog/resource-capabilities` and `POST /v1/catalog/offerings`
  (`catalog.manage`) create the capability vocabulary and one Offering plus
  its initial immutable OfferingVersion and requirements in one transaction;
- `PUT /v1/catalog/offerings/{id}/booking-policy` (`catalog.manage`) appends
  an override revision to the append-only
  `offering_version_booking_policies` ledger (migration 0033). The effective
  policy is the highest-revision row or the bootstrap
  `offering_versions.booking_policy`; UPDATE/DELETE are rejected by trigger;
  existing Reservations keep their frozen snapshot;
- the operational location/hours/exception surfaces plus
  `PUT /v1/operations/organization/holidays`, which materializes each declared
  date as one full-day `unavailable` hours exception per active Location in
  its timezone;
- `read_catalog_supply` (via `contracts/onboarding.py`) backs the
  `locations`/`no_bookable_offering` facts of `GET /v1/onboarding/readiness`.

Catalog provides structured operational truth for agents/applications; it is not a universal CMS or RAG system.
