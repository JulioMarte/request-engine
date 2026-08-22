# 0012 — Contextual Resource-at-Location Supply

Status: Proposed

## Context

The released V3 booking baseline intentionally kept `Resource` as the concrete capacity root and deferred a separate `ResourceAssignment` concept because no initial use case demonstrated independently mutable execution assignment.

Post-V3 product requirements now demonstrate that need.

A physician or other Resource may work:

```text
at multiple Locations
on different days/hours per Location
with different Offerings per Location
with different fixed price/duration terms per Resource + Location + Offering context
```

Example:

```text
Dr. Pérez

Clínica Brugal
  Tue/Thu 13:00-17:00
  Cardiology
  DOP 3,500
  45 minutes

Clinic B
  Fri 08:00-12:00
  Cardiology
  DOP 4,000
  30 minutes
```

A single ambiguous `Resource.schedule` or mutable Resource-level price cannot represent this truth safely.

At the same time, Request Engine must preserve the minimal V3 capacity model:

```text
Resource = local capacity/serialization root
CapacityClaim = authoritative capacity-consumption ledger
```

The new configuration must not become a second capacity ledger or an excuse for a universal configuration/pricing engine.

## Decision

Introduce an explicit effective-dated **Resource-at-Location assignment** concept in Booking, provisionally/canonically described as `ResourceLocationAssignment` until implementation proves the final persisted name.

The assignment means:

> this tenant-local Resource is operationally allowed to work at this Location during this effective period.

It does not consume capacity.

Recurring availability that differs by Location is scoped to that Resource-at-Location context rather than treated as one universal Resource schedule.

Concrete booking supply may also have a narrow Resource + Location + OfferingVersion effective context carrying booking-specific overrides required to quote and reserve the appointment, initially limited to deterministic fixed commercial/operational terms such as:

```text
price amount/currency
planned duration
bookable state
accepted booking-policy reference when required
```

`OfferingVersion` remains the catalog/versioned service contract and may provide base/default terms. Contextual booking terms override only the exact Resource + Location + OfferingVersion scope and effective time.

The accepted F1 resolution order is:

```text
exact effective Resource + Location + OfferingVersion booking context
>
OfferingVersion base/default term
>
missing required term => not quoteable/bookable for that capability
```

No hidden arbitrary inheritance graph is introduced.

Existing V3 Resources without contextual assignments retain legacy behavior until explicitly configured/migrated.

A successful Reservation preserves immutable/explainable commercial commitment. Later configuration changes cannot retroactively change the committed price or historical meaning of existing Reservations/CapacityClaims.

## Consequences

### Positive

- one physician can be modeled correctly across several clinics/locations;
- schedules stop being ambiguous when they differ by Location;
- price and planned duration can be resolved deterministically for the exact bookable context;
- future cross-tenant/geospatial discovery has a trustworthy source of operational supply;
- future natural-language configuration can target semantic commands instead of arbitrary metadata;
- released V3 `CapacityClaim` authority remains unchanged;
- existing shared-capacity cross-tenant serialization remains compatible because the Resource is still the local capacity root.

### Costs

- Booking gains additional configuration rows and revalidation work before capacity mutation;
- effective-dated overlap rules and stale-option races must be explicitly tested;
- cross-module contracts between Catalog Location/Offering truth and Booking Resource context become more important;
- existing Resource-scoped schedules require a backward-compatibility path.

### Required safeguards

- ResourceLocationAssignment cannot cross Organization boundaries;
- overlapping effective assignments/configuration for one exact scope cannot be ambiguous;
- contextual configuration cannot duplicate CapacityClaim consumption truth;
- assignment retirement cannot rewrite historical Reservation/Claim meaning;
- `appointments.book` revalidates contextual configuration after `find_slots`;
- materially changed price between option discovery and booking causes stale/conflict behavior, never silent substitution;
- no external provider/geocoding I/O occurs while authoritative locks are held.

## Rejected alternatives

### Keep one Resource-level schedule

Rejected because the same physician may work different hours at different Locations. One schedule would either over-advertise availability or require implicit ad-hoc metadata rules.

### Put everything in `operational_config JSONB`

Rejected because pricing, schedules, assignments and tenant ownership have relational invariants, effective-date races and historical provenance requirements that an unbounded configuration document would weaken.

### Make ResourceLocationAssignment another capacity ledger

Rejected. `CapacityClaim` remains the sole authoritative local capacity-consumption truth. Assignment is configuration/eligibility, not consumption.

### Create a universal pricing engine now

Rejected. The demonstrated requirement is deterministic fixed contextual booking price/duration. Formula DSLs, surge pricing, insurance adjudication, coupons and auctions are not justified.

### Create a new generic `configuration` bounded context

Rejected. Ownership remains with existing business modules: tenancy for Organization authority/defaults, catalog for Location/Offering truth, booking for Resource capacity/context.

### Rewrite the released V3 baseline history

Rejected. V3 baseline documents/migration history remain provenance; this decision is a post-V3 extension implemented through append-only contracts/migrations.

## Acceptance condition

This ADR remains `Proposed` until the feature implementation proves:

```text
clean + upgraded database paths
Resource-at-Location isolation/cardinality
effective-dated conflict handling
stale option behavior
historical Reservation price provenance
legacy booking compatibility
shared-capacity compatibility
tenant/RLS boundaries
```

After that proof and merge, the ADR may be marked `Accepted`.