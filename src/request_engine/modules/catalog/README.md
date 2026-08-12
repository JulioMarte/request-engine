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

Catalog provides structured operational truth for agents/applications; it is not a universal CMS or RAG system.
