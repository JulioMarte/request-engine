# Operational Profile & Contextual Supply — Feature Plan

Status: active design/implementation plan for `feature/operational-profile-contextual-supply`.

Base: `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573` (post-V3 baseline, after documentation reconciliation PR #74).

This document defines the complete scope, sequencing, design constraints, invariants, implementation phases and acceptance criteria for the first post-V3 feature in the operational-profile/discovery roadmap.

It is intentionally narrower than cross-tenant discovery, live service operations, operational projections, recovery communications and the natural-language operational copilot. Those later features depend on the contracts established here.

---

## 1. Product objective

Request Engine must become authoritative for the structured operational facts required to answer and execute questions such as:

```text
Can I book a cardiology consultation tomorrow between 1 PM and 5 PM
at Clínica Brugal, with any eligible doctor, and what will it cost?
```

The answer must not require Directus, a CMS, RAG, Memory or manual orchestration across unrelated systems for operational truth.

The system must be able to determine, from Request Engine state alone:

```text
what service exists
which version applies
where it can be delivered
which Resources are eligible
when each Resource is actually available at that Location
which operational hours constrain the service
which exceptions apply
how long the visit is planned to take
what price applies in that context
whether the resulting concrete option is bookable
```

Directus remains presentation/content authority. Memory remains learned customer-context authority. Request Engine owns operational truth.

Core boundary:

> If a fact is necessary to determine whether, where, when, with whom, for how long or under what commercial/operational conditions an operation may be executed, that fact belongs in Request Engine or in an explicit authoritative provider contract consumed by Request Engine.

---

## 2. Non-goals

This feature does NOT implement:

```text
cross-tenant marketplace/discovery search
platform-wide discovery tokens
popularity ranking
Google reviews / Google Business enrichment
live queue workload projection
same-day adaptive intake closure
ServiceSession execution telemetry
emergency / medical-representative operational activities
patient ETA prediction
end-of-day shortfall recovery
rescheduling campaigns
natural-language configuration assistant
EHR/EMR/clinical records
medical notes, diagnoses or medications
CRM or CMS functionality
route optimization
mobile service-area dispatch
universal pricing engine
machine-learned automatic policy mutation
```

The schema/contracts must not block those later features, but they must not be implemented speculatively here.

---

## 3. Architectural position

This feature extends existing V3 baseline modules rather than creating a universal configuration module.

### `tenancy`

Owns:

```text
Organization identity
Principal/Representation authority
minimal operational tenant profile defaults
```

Candidate Organization operational defaults:

```text
legal_name
public/display_name
default_timezone
default_locale
default_currency
status
```

These fields must remain minimal. Do not create an unbounded `operational_config JSONB` god object.

### `catalog`

Owns stable/versioned commercial and structured business truth:

```text
Location
Offering
OfferingVersion
ResourceCapability vocabulary
OfferingResourceRequirement
visit/service variant vocabulary if introduced as Offering-owned configuration
structured public operational information
```

Location gains first-class geospatial coordinates because future discovery must calculate physical proximity without external geocoding on every query.

### `booking`

Owns capacity and concrete Resource availability:

```text
Resource
ResourceCapability assignment
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
Resource-at-Location operational assignment if accepted
contextual availability needed for concrete booking
```

The existing V3 rule postponing `ResourceAssignment` is re-opened by a concrete product requirement: the same physician/resource may work at different Locations on different days and may expose different services, prices, durations and schedules in each context. The implementation must prove the new concept is independently mutable execution/availability configuration and not duplicate CapacityClaim truth.

No new generic `configuration` bounded context is introduced.

---

## 4. Domain scenarios the feature MUST support

### 4.1 Physician working at multiple locations

```text
Dr. Pérez

Clínica Brugal
  Tue/Thu 13:00-17:00
  Cardiology
  DOP 3,500
  45 minutes

Clínica B
  Fri 08:00-12:00
  Cardiology
  DOP 4,000
  30 minutes
```

The model must not store one ambiguous `Resource.schedule` and pretend it applies everywhere.

### 4.2 Location operational hours

```text
Clínica Brugal open 08:00-18:00
Dr. Pérez present 13:00-17:00
Cardiology available 13:00-17:00
```

Final bookable capacity is constrained by all applicable authoritative layers.

### 4.3 Temporary schedule exception

Examples:

```text
"This Friday I stop at 2 PM."
"I will not work next Monday."
"This Tuesday I will work until 7 PM."
"Block 12 PM to 1 PM for lunch."
```

These must be representable as effective-dated exceptions without rewriting the recurring baseline schedule.

### 4.4 Future price change

```text
Current cardiology price: DOP 3,500
From 2026-09-01: DOP 4,000
```

Reservations confirmed before the change retain the commercial commitment under which they were booked. No later configuration edit may retroactively change their agreed price/provenance.

### 4.5 Different price/duration by Resource + Location

The same OfferingVersion may require contextual commercial/operational terms:

```text
Dr. Pérez @ Brugal  = DOP 3,500 / 45m
Dr. Pérez @ Clinic B = DOP 4,000 / 30m
```

The design must decide explicitly whether these are overrides of OfferingVersion defaults, separate effective-dated contextual terms, or a different versioning model. Precedence must be deterministic and explainable.

### 4.6 Visit/service variants

A physician may distinguish operationally:

```text
new patient consultation
follow-up
results review
procedure
```

These are not a universal clinical taxonomy. They are tenant/Offering-owned operational variants with explicit planned duration and potentially contextual price. The design must determine whether they are distinct Offerings, OfferingVersions, or versioned child variants. Avoid parallel lifecycle duplication.

### 4.7 Time-window query

The capability layer must be able to express:

```text
2026-08-21 13:00-17:00
```

for natural-language intents such as:

```text
"tomorrow afternoon"
"between 1 and 5"
"after 2"
```

Natural-language parsing is outside this feature. Request Engine receives normalized temporal constraints and applies timezone-aware operational rules.

---

## 5. Location and geospatial contract

`Location` must represent a physical operational place, not a Resource's identity.

Candidate fields/concepts:

```text
id
organization_id
name
status
timezone
address fields
latitude
longitude
geocoding_source?
geocoded_at?
revision/effective state as required
```

Requirements:

- Coordinates are normalized and authoritative enough for future distance calculations.
- Coordinates must be validated to legal latitude/longitude ranges.
- A Location participating in future geospatial discovery must have usable coordinates.
- Booking must not call Google Maps/Mapbox/etc. to determine distance during ordinary availability queries.
- External geocoding is an ingestion/configuration concern and must not run while authoritative DB locks are held.
- Do not introduce `ServiceArea` for physical-clinic discovery. Future `ServiceArea` means an area where a mobile service may be delivered; proximity to a fixed Location is a separate concept.
- PostGIS adoption is allowed only if justified by the implementation/query plan; do not add it merely because coordinates exist.

---

## 6. Schedule composition contract

The final operational availability must be deterministic and explainable.

The design must formalize the intersection/precedence among at least:

```text
Organization operational defaults (only if operationally meaningful)
Location operational hours
Resource-at-Location recurring availability
Offering/visit-variant restrictions when required
ScheduleException
existing CapacityClaims/Holds/Reservations
```

Preferred principle:

```text
base schedules define potential availability
exceptions narrow or extend a specific effective period
capacity claims consume otherwise-valid availability
```

No hidden magic inheritance is permitted. If an override system exists, precedence must be documented, testable and returned in provenance where useful.

Timezones:

- Persistent intervals use timezone-safe timestamps according to existing V3 conventions.
- Recurring local schedules are interpreted in the owning Location/resource operational timezone.
- DST behavior must be explicit even if the initial target locale is Dominican Republic.
- API presentation timezone is not authority for schedule calculation.

---

## 7. Contextual commercial terms and historical price commitment

This feature must establish a narrow pricing contract without becoming a pricing engine.

Supported initial semantics should cover:

```text
base/default OfferingVersion price
Resource/Location contextual price when explicitly configured
effective dating
currency
planned duration
visit variant contextual terms if accepted
```

Explicitly out of scope initially:

```text
percentage formulas
dynamic surge pricing
insurance adjudication
coupons/promotions engine
complex tax calculation
auctions
ML pricing
arbitrary expression language
```

Reservation history requirement:

A confirmed Reservation must preserve the exact commercial terms required to explain the booking later, including at minimum:

```text
currency
committed amount or immutable price reference
pricing/context provenance sufficient to explain why it applied
OfferingVersion reference
```

Changing future operational configuration must never mutate the historical commitment of an already-confirmed Reservation.

The implementation must explicitly choose between snapshot + provenance and immutable referenced commercial-version records. Do not depend on mutable joins to reconstruct historical price.

---

## 8. Resource-at-Location / contextual supply model

A core design task is to determine the minimal explicit model for:

```text
Resource
  × Location
  × OfferingVersion / operational visit variant
  × effective time
  × schedule
  × price/duration/policy overrides
```

Candidate conceptual decomposition:

```text
ResourceLocationAssignment
  resource_id
  location_id
  effective_from/effective_until
  status

ResourceOfferingContext
  assignment_id
  offering_version_id or visit_variant_id
  effective commercial terms
  booking-relevant context
```

Names are provisional.

Hard constraints:

- Do not duplicate CapacityClaim as a second capacity ledger.
- Do not create independent execution state in this feature.
- Do not make mutable assignment history capable of rewriting the meaning of existing Reservations/Claims.
- If assignment/configuration is referenced by authoritative historical state, effective dating/immutability/revision rules must preserve provenance.
- Cross-module imports must use contracts surfaces.
- No generic CRUD repository should replace semantic persistence adapters.

---

## 9. Public/application capability target

Existing capabilities remain capability-oriented rather than entity CRUD.

This feature should evolve/extend the semantics of:

```text
business.get_info
catalog.search_offerings
catalog.get_offering
appointments.find_slots
appointments.book
```

Desired normalized query example:

```text
appointments.find_slots(
  offering = cardiology,
  location = Clinica Brugal,
  window = 2026-08-21T13:00..17:00,
  resource_preference = any
)
```

Desired option result may include policy-permitted fields such as:

```text
option/token
resource/provider display info
Location
start_at
end_at
planned duration
applicable amount/currency
commercial provenance/reference as appropriate
```

`find_slots` remains advisory and creates no capacity commitment. `appointments.book` revalidates authoritative state and commercial/context rules according to the accepted contract.

The implementation must decide whether an option token pins an observed price/config revision and what happens when price/config changes between `find_slots` and `book`.

That race MUST be specified and tested; silent price substitution is not acceptable.

---

## 10. Authorization and authority model

This feature remains tenant-scoped.

It does NOT add cross-tenant discovery authority.

Actors may eventually include physician, secretary, clinic admin and platform service, but this feature only adds permissions actually required by the implemented commands.

Rules:

- Possession of IDs never grants authority.
- Organization remains the security boundary.
- Resource-specific configuration changes require authenticated Principal + valid Representation/permission semantics.
- Secretary/doctor fine-grained roles may be prepared only when a concrete command needs them; do not prebuild a universal RBAC product.
- `request_engine_admin` must not become the normal application path for configuring physician operational state.
- RLS/tenant context remains defense-in-depth.
- Natural-language assistant authority is out of scope; later assistants must call the same semantic commands rather than direct DB mutation.

---

## 11. PostgreSQL / migration rules

This is post-V3 production evolution.

Non-negotiable:

```text
DO NOT edit migrations/versions/0001_initial.py
DO NOT append product changes to migrations/sql/v3_candidate/
DO NOT mutate historical V2 design-chain files
```

Schema evolution uses a new append-only Alembic revision after `0001_initial` according to repository migration policy.

Database responsibilities may include:

```text
relational/cardinality constraints
effective-date integrity where feasible
tenant ownership consistency
immutable historical references
coordinate range checks
currency/amount structural constraints
schedule/exception integrity backstops
race-sensitive uniqueness/exclusion constraints where required
```

Python owns:

```text
semantic command/query validation
policy resolution
context precedence orchestration
authorization
transaction framing
option/price resolution semantics
external geocoding adapter orchestration if later implemented
```

No external I/O while authoritative DB locks are held.

---

## 12. Concurrency and race questions that MUST be closed

Before implementation is considered complete, the design must specify and tests must falsify at least:

1. Price changes after `find_slots` but before `book`.
2. Resource-location assignment revoked after option discovery but before booking.
3. Schedule exception created after option discovery but before booking.
4. Location hours changed while booking is attempted.
5. Offering/visit variant becomes inactive after discovery.
6. Concurrent conflicting effective-dated contextual-term writes.
7. Concurrent schedule edits that would create ambiguous overlapping active configuration.
8. Existing Reservation remains explainable after assignment/price/schedule changes.
9. Existing CapacityClaim provenance cannot be invalidated by config mutation.
10. Two Resources/Locations with same display names never become authority-confused; IDs remain canonical.
11. Timezone boundary and DST cases do not produce duplicate/invalid intervals.
12. Cross-tenant guessed IDs are rejected/opaque according to existing security contracts.

Booking success must always mean the concrete option was revalidated under authoritative current state inside the correct transaction protocol.

---

## 13. Data migration/backward compatibility

The existing V3 baseline contains tenant-local Resources, schedules, Locations and Offering relationships.

The implementation plan must include an explicit compatibility strategy:

```text
existing Resources without contextual assignments
existing AvailabilitySchedules
existing Reservations/Claims
existing Locations without coordinates
existing OfferingVersions
```

Preferred rule:

- Existing V3 behavior continues to work without requiring immediate backfill of optional new contextual features.
- New contextual semantics activate only when the relevant configuration exists.
- No migration may reinterpret old historical Reservations or Claims.
- Coordinates may be nullable for legacy/non-discovery Locations unless the accepted contract proves a stronger invariant is safe.

Any mandatory backfill must be deterministic, reviewable and tested on clean + upgraded databases.

---

## 14. Implementation phases

### Phase A — architecture reconciliation

Before schema code:

1. Compare this feature against current normative documents.
2. Amend `docs/v3/01-capability-contracts.md` where public semantics change.
3. Amend `docs/v3/02-pre-sql-contract.md` with cardinalities, transaction/race rules and invariants.
4. Amend `docs/10-module-ownership-map.md` if Resource-at-Location/contextual commercial ownership changes.
5. Add/accept an ADR if the ResourceAssignment/contextual-supply decision is sufficiently durable/hard-to-reverse.
6. Ensure docs describe post-V3 append-only migration rules.

No schema implementation should outrun this contract.

### Phase B — relational schema

Implement the minimal accepted entities/columns/constraints in a new Alembic revision.

Prove:

```text
clean bootstrap
upgrade from 0001_initial
repeat bootstrap
schema/catalog assertions
RLS/privilege boundaries
historical baseline immutability
```

### Phase C — domain/application model

Add only structures required by real behavior:

```text
domain value objects/entities
commands
queries
ports
semantic repositories
cross-module contracts
```

Do not create empty architecture folders.

### Phase D — operational configuration commands

Candidate commands, subject to final naming:

```text
UpdateOrganizationOperationalProfile
Create/UpdateLocationOperationalInfo
SetLocationOperationalHours
AssignResourceToLocation
ChangeResourceLocationAvailability
CreateScheduleException
ConfigureOfferingContext
ScheduleFutureContextualTerms
RetireResourceLocationAssignment
```

Each write must define:

```text
authority
idempotency
expected revision where needed
transaction boundary
invariants
machine-readable failures
audit provenance
```

### Phase E — query resolution

Implement deterministic read resolution for:

```text
business info
Offering context
Resource-at-Location eligibility
applicable schedule
applicable contextual duration/price
```

### Phase F — booking integration

Extend `appointments.find_slots` and `appointments.book` to consume accepted contextual supply contracts without weakening existing capacity locking.

Prove stale-option/config races and historical price commitment.

### Phase G — tests and adversarial proof

Run the repository quality/architecture suite plus new focused tests.

No merge-readiness claim based only on happy-path unit tests.

---

## 15. Required test matrix

### Domain/application tests

- Organization defaults validation.
- Location coordinate/timezone validation.
- Resource assigned to one/multiple Locations.
- Same Resource different schedules by Location.
- Same Resource/Offering different price/duration by Location.
- Future price effective date.
- Schedule exception remove/extend availability.
- Visit/service variants.
- Precedence resolution.
- Historical Reservation commercial commitment.

### PostgreSQL/integration tests

- Tenant consistency across every new FK/path.
- RLS/role restrictions.
- Effective-dated overlap rejection if model requires it.
- Historical-reference immutability.
- Clean migration + upgrade from baseline.
- Concurrent config changes.
- Option-staleness races.
- Booking capacity race remains correct under contextual config.

### API/capability tests

- `business.get_info` exposes only public operational fields.
- `catalog` returns version/context-correct information.
- `find_slots` within an explicit 13:00-17:00 window.
- `find_slots` with `resource=any` resolves eligible providers.
- Option includes correct Location/duration/price where policy permits.
- Booking revalidates stale price/schedule/resource context.
- Machine-readable errors do not leak foreign tenant information.

### Regression tests

- Existing tenant-local booking remains valid when no new contextual config is present.
- Existing shared-capacity cross-tenant mutex behavior remains intact.
- Queue, waitlist, communications and worker assembly behavior remain unchanged unless explicitly touched through a contract.

---

## 16. Acceptance scenarios

The feature is not complete until all of the following are demonstrable.

### Scenario A

```text
"Cardiologist at Clínica Brugal tomorrow between 1 and 5."
```

RE returns only Resources actually eligible and available there during that window, with applicable duration and price.

### Scenario B

Dr. Pérez works at two clinics with different schedules/prices. RE returns the correct context for each Location without conflating them.

### Scenario C

A future price increase is configured. New bookings after the effective boundary use the new price; existing confirmed Reservations remain historically at the old committed price.

### Scenario D

A one-day exception shortens the physician's schedule. Slots outside the exception-adjusted schedule disappear; recurring schedule remains unchanged for other dates.

### Scenario E

A stale option discovered before a schedule/price/config change cannot be booked under obsolete assumptions without explicit contract behavior. Booking either re-resolves under a documented accepted rule or returns a machine-readable stale/conflict response.

### Scenario F

Legacy V3 Resources without contextual assignments continue existing behavior according to the backward-compatibility contract.

---

## 17. Definition of Done

This feature may be considered ready for merge only when:

- normative docs and ownership are reconciled;
- any durable architecture decision has an ADR;
- a new append-only Alembic migration implements only the accepted schema;
- `0001_initial`, frozen V3 candidate and V2 history remain untouched;
- Python implementation follows module-first boundaries;
- no unbounded operational-config JSONB god object is introduced;
- Resource-at-Location semantics are explicit and race-safe;
- schedule precedence/exceptions are deterministic;
- contextual price/duration resolution is deterministic;
- historical Reservation commercial commitments are immutable/explainable;
- `find_slots` and `book` close stale configuration races;
- tenant isolation and existing shared-capacity behavior remain intact;
- clean bootstrap + upgrade + architecture + PostgreSQL + application suites pass;
- adversarial tests cover the race matrix above;
- documentation clearly marks later discovery/live-operations/copilot work as separate features.

---

## 18. Roadmap unlocked by this feature

After merge to `development`, branch the next work from the new head:

```text
feature/geospatial-cross-tenant-discovery
feature/live-service-operations
```

Then:

```text
live-service-operations
  -> live-capacity-projection
  -> operational-recovery-communications

operational-profile/contextual-supply
  + recovery/config commands
  -> operational-copilot-control-plane
```

This branch establishes the vocabulary and authoritative configuration contracts those features must consume. They should not pre-empt or duplicate this feature's source of truth.
