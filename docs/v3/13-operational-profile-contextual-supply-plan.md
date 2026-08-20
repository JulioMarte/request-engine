# Operational Profile & Contextual Supply — Feature Plan

Status: active design/implementation plan for `feature/operational-profile-contextual-supply`.

Base: `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573` (post-V3 baseline, after documentation reconciliation PR #74).

Normative F1 contract:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
```

Complete F1–F6 product/design direction:

```text
docs/v3/14-operational-intelligence-roadmap.md
```

Durable rationale:

```text
docs/adr/0012-contextual-resource-location-supply.md
```

This document defines the implementation scope, sequencing, proof obligations and Definition of Done for F1 only. Later cross-tenant discovery, live service operations, operational projections, recovery communications and the natural-language operational copilot are deliberately separate features even though their accepted direction is preserved in the roadmap.

---

## 1. Product objective

Request Engine must become authoritative for the structured operational facts required to answer and execute questions such as:

```text
Can I book a cardiology consultation tomorrow between 1 PM and 5 PM
at Clínica Brugal, with any eligible doctor, and what will it cost?
```

The answer must not require Directus, a CMS, RAG, Memory or manual orchestration across unrelated systems for operational truth.

RE must be able to determine:

```text
what service exists
which OfferingVersion applies
where it can be delivered
which Resources are eligible
when each Resource actually works at that Location
which Location hours constrain the service
which schedule exceptions apply
how long the appointment is planned to take
what fixed price applies in that exact context
whether the concrete option is currently bookable
```

It must also provide the minimum public operational profile needed to act without a CMS, including:

```text
business display identity
Location address
Location timezone
Location operational hours
Location public operational contact endpoints
```

Directus remains presentation/content authority. Memory remains learned customer-context authority. Request Engine owns operational truth.

Core boundary:

> If a fact is necessary to determine whether, where, when, with whom, for how long or under what commercial/operational conditions an operation may be executed, that fact belongs in Request Engine or in an explicit authoritative provider contract consumed by Request Engine.

---

## 2. F1 scope

F1 implements only the foundational tenant-scoped operational model.

### Included

```text
minimal Organization operational profile defaults
Location structured address/timezone/status
Location public operational contact endpoints
Location recurring operational hours
normalized Location latitude/longitude
Resource-at-Location effective assignment
Resource-at-Location recurring availability
Resource schedule exceptions scoped to the affected context
Offering/OfferingVersion defaults
contextual Resource + Location + OfferingVersion fixed price/duration
future effective contextual terms
historical Reservation price/currency provenance
normalized time-window slot queries
stale option/config revalidation
backward compatibility with released V3 booking
```

### Explicitly not implemented in F1

```text
cross-tenant marketplace/discovery search
platform-wide discovery token/authority
popularity ranking
Google reviews / Google Business enrichment
distance/radius marketplace search itself
live queue workload projection
same-day adaptive intake closure
ServiceSession execution telemetry
emergency / medical-representative operational activities
patient ETA prediction
end-of-day shortfall recovery
rescheduling campaigns driven by live shortfall
natural-language configuration assistant
EHR/EMR/clinical records
medical notes, diagnoses or medications
CRM or CMS functionality
route optimization
mobile ServiceArea dispatch
universal pricing engine
machine-learned automatic policy mutation
```

These are preserved in `14-operational-intelligence-roadmap.md`; they are not lost or silently rejected.

---

## 3. Architectural position

F1 extends the existing modular-monolith baseline. It does not create a generic configuration module.

### `tenancy`

Owns:

```text
Organization identity
Principal/Representation authority
minimal operational tenant defaults
Party / PartyContactPoint identity remains separate
```

Organization defaults are typed and narrow:

```text
legal_name
public/display_name
default_timezone
default_locale
default_currency
status
```

Do not create an unbounded `operational_config JSONB` god object.

### `catalog`

Owns:

```text
Location identity/public operational profile
Location structured address
Location public operational contact endpoints
Location operational hours
Location geospatial coordinates
Offering
OfferingVersion
ResourceCapability vocabulary
OfferingResourceRequirement
base/default commercial terms
```

Public Location endpoints are not a CRM profile and are not a substitute for PartyContactPoint identity.

### `booking`

Owns:

```text
Resource
ResourceCapability assignment
Resource-at-Location assignment
Resource-at-Location recurring availability
Resource schedule exceptions
booking-specific contextual terms
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Resource remains the local capacity/serialization root. CapacityClaim remains the authoritative capacity-consumption ledger.

The new Resource-at-Location concept represents eligibility/configuration, not capacity consumption.

---

## 4. Durable model decision

The released V3 baseline explicitly deferred `ResourceAssignment` until a real independently mutable execution/assignment requirement existed.

That requirement now exists:

```text
one physician/resource
-> multiple Locations
-> different days/hours by Location
-> potentially different bookable Offerings by Location
-> different fixed price/duration by Resource + Location + OfferingVersion
```

F1 therefore introduces an explicit effective-dated Resource-at-Location assignment, conceptually/canonically described as:

```text
ResourceLocationAssignment
```

until implementation proves the final persisted name.

Hard rules:

```text
assignment does not consume capacity
assignment cannot cross Organization boundaries
ambiguous overlapping effective configuration is forbidden
retiring assignment cannot rewrite historical Reservation/Claim meaning
shared-capacity binding still applies to the underlying Resource
```

ADR 0012 records the rationale and remains `Proposed` until implementation/evidence proves it.

---

## 5. Required domain scenarios

### 5.1 Physician at multiple Locations

```text
Dr. Pérez

Clínica Brugal
  Tue/Thu 13:00-17:00
  Cardiology - New Consultation
  DOP 3,500
  45 minutes

Clinic B
  Fri 08:00-12:00
  Cardiology - New Consultation
  DOP 4,000
  30 minutes
```

RE must never conflate those contexts.

### 5.2 Location hours constrain Resource availability

```text
Clínica Brugal open 08:00-18:00
Dr. Pérez present 13:00-17:00
bookable interval must fit both
```

A Resource schedule alone cannot make a physical Location available while the Location is closed unless an explicit exception/additional-hours rule makes the Location operational.

### 5.3 Temporary schedule exceptions

Must represent without rewriting recurrence:

```text
This Friday I stop at 2 PM.
I will not work next Monday.
This Tuesday I will work until 7 PM.
Block 12 PM to 1 PM for lunch.
```

An exception targeted to one Resource/Location context must not accidentally modify that Resource at another Location.

### 5.4 Future price change

```text
current = DOP 3,500
from 2026-09-01 = DOP 4,000
```

Fresh bookings after the effective boundary use the new terms. Existing confirmed Reservations preserve the old committed amount/currency.

### 5.5 Different price/duration by Resource + Location

```text
Dr. Pérez @ Brugal  = DOP 3,500 / 45m
Dr. Pérez @ Clinic B = DOP 4,000 / 30m
```

Exact contextual terms override OfferingVersion defaults only for that exact effective scope.

### 5.6 Operational visit types

F1 does not create a parallel universal `VisitVariant` aggregate.

When an operational visit type has independently meaningful price, duration or booking semantics, model it as a distinct Offering/OfferingVersion that can share a searchable service/category family:

```text
Cardiology - New Consultation
Cardiology - Follow-up
Cardiology - Results Review
```

Future live-operation classification may distinguish expected from actual service type, but it must not rewrite the booked OfferingVersion.

### 5.7 Time-window query

Natural-language interfaces may understand:

```text
tomorrow afternoon
between 1 and 5
after 2
```

but F1 Booking receives normalized temporal constraints such as:

```text
2026-08-21 13:00-17:00
```

Natural-language parsing stays outside Booking.

### 5.8 Public operational contact information

Without Directus, `business.get_info` must be able to provide safe operational facts such as:

```text
Clínica Brugal
address
phone/WhatsApp/email endpoints explicitly marked public
operational hours
timezone
```

Possession of a contact endpoint never grants authority.

---

## 6. Location and geospatial foundation

`Location` represents a physical operational place.

Required concepts:

```text
id
organization_id
name
status
timezone
structured address
latitude?
longitude?
geocoding_source?
geocoded_at?
revision/effective metadata as required
```

Coordinate requirements:

```text
-90 <= latitude <= 90
-180 <= longitude <= 180
both coordinates present or both absent
```

F1 persists trustworthy normalized coordinates so F2 can calculate proximity without calling Google/Mapbox for every discovery query.

External geocoding is an ingestion/configuration concern and cannot run under authoritative DB locks.

F1 does **not** introduce `ServiceArea` for fixed clinics. Future `ServiceArea` means where a mobile service can actually be delivered; proximity to a fixed Location is a different concept.

PostGIS is optional and must be justified by the F2 query/index plan rather than added speculatively in F1.

---

## 7. Public Location contact endpoints

A Location may expose `0..N` structured public operational contact endpoints.

Initial supported kinds may include:

```text
phone
whatsapp
email
```

The accepted schema must provide:

```text
tenant consistency
normalization/validation appropriate to kind
active/public state
stable purpose/label only if operationally needed
```

Do not turn this into arbitrary customer/contact management.

PartyContactPoint remains a separate tenancy concept for Parties and communication identity.

---

## 8. Schedule composition

For contextual Resource booking, final potential availability is deterministic:

```text
Location operational hours
INTERSECT
Resource-at-Location recurring availability
INTERSECT
explicit Offering/context temporal eligibility when configured
APPLY
ScheduleException / additional availability
THEN
capacity revalidation against Holds/Claims/Reservations
```

### 8.1 Organization hours

Organization may expose general business hours for informational purposes, but multi-location booking must not silently inherit one Organization schedule into every Location.

Physical bookings are constrained by the selected Location.

### 8.2 Exception semantics

Exceptions may:

```text
remove availability
shorten a day
add availability
extend one day
block a local sub-range
```

They never rewrite the recurring baseline schedule.

### 8.3 Timezones

Recurring local schedules are interpreted in the Location IANA timezone.

Concrete authoritative intervals use timezone-aware instants and half-open `[start,end)` semantics.

DST ambiguity/nonexistent local times must be explicit even if the initial Dominican target does not use DST.

Presentation timezone never becomes schedule authority.

---

## 9. Contextual commercial terms

F1 deliberately implements only a narrow deterministic price contract.

### Supported

```text
fixed amount
currency
OfferingVersion default
exact Resource + Location + OfferingVersion effective override
planned duration
effective dating
```

### Resolution precedence

```text
exact effective Resource + Location + OfferingVersion context
>
OfferingVersion base/default
>
required term missing => not quoteable/bookable
```

No hidden arbitrary inheritance graph is allowed.

### Explicitly out of scope

```text
percentage/expression formulas
dynamic surge pricing
insurance adjudication
coupons/promotions engine
complex tax engine
auctions
ML pricing
```

---

## 10. Historical Reservation commercial commitment

A confirmed Reservation must preserve enough immutable information to explain later what was agreed.

At minimum:

```text
committed amount
currency
OfferingVersion reference
context/revision/provenance sufficient to explain why those terms applied
```

Changing future price, schedule, assignment or Location configuration must never retroactively change that historical commitment.

Do not reconstruct historical price exclusively through mutable current joins.

Legacy Reservations created before F1 are not rewritten to invent provenance they never captured.

---

## 11. `find_slots` and `book` semantics

F1 extends existing capability semantics without exposing CRUD internals.

### `business.get_info`

May return safe structured operational data:

```text
Organization display identity
Locations
addresses
public Location contact endpoints
Location hours/timezone
```

### `catalog.search_offerings` / `catalog.get_offering`

Remain version-aware and can filter/describe applicable Location/effective service context without promising concrete Resource capacity until Booking resolves it.

### `appointments.find_slots`

Normalized input can include:

```text
offering/version
Location
explicit time window
subject when eligibility depends on it
resource preference = any or explicit Resource
presentation timezone
```

AppointmentOption may include:

```text
opaque option token/id
Resource/provider display info when policy allows
Location
start/end
planned duration
applicable amount/currency
opaque configuration observation/fingerprint
```

The option is advisory and creates no capacity commitment.

### `appointments.book`

Inside the authoritative transaction, revalidate:

```text
tenant/authority
OfferingVersion state
ResourceLocationAssignment state
Location hours
Resource-at-Location schedule
exceptions
contextual terms
capacity
shared-capacity root when applicable
```

Success persists capacity + Reservation + historical commercial commitment coherently.

---

## 12. Stale option policy

This decision is closed for F1:

> A material price/context change after `find_slots` causes stale/conflict behavior. `book` never silently substitutes a materially different price.

The caller receives a machine-readable response directing it to obtain fresh options.

The option token/fingerprint must be sufficient to detect relevant material configuration changes.

The same advisory/revalidation principle applies when assignment/schedule/Offering state changes: stale discovery cannot override current authority.

---

## 13. Authorization

F1 is tenant-scoped.

No platform-wide discovery authority is implemented here.

Configuration requires:

```text
authenticated Principal
Organization context
specific Representation/permission for target scope
```

Future roles are preserved in the roadmap, but F1 adds only permissions required by actual commands.

Rules:

```text
IDs do not grant authority
request_engine_admin is not normal clinic configuration authority
cross-tenant guessed IDs remain opaque/rejected
RLS remains defense-in-depth
future LLM assistant calls semantic commands, never SQL/direct tables
```

---

## 14. Candidate semantic commands

Names may be refined during implementation, but responsibilities must remain explicit:

```text
UpdateOrganizationOperationalProfile
CreateLocation
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationPublicContactEndpoints
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
CreateResourceScheduleException
ChangeResourceScheduleException
ConfigureBookingContextTerms
ScheduleFutureBookingContextTerms
```

Each network/agent retryable write defines:

```text
idempotency
authority
expected revision/stale intent behavior
transaction boundary
invariants
machine-readable failures
audit provenance
```

No generic CRUD endpoint substitutes for semantic commands.

---

## 15. PostgreSQL and migration rules

F1 is post-V3 append-only evolution.

Non-negotiable:

```text
DO NOT edit migrations/versions/0001_initial.py
DO NOT append F1 product changes to migrations/sql/v3_candidate/
DO NOT mutate migrations/sql/design_chain/ history
```

New schema uses new Alembic revision(s) after the baseline.

PostgreSQL owns/backstops:

```text
same-Organization relationships
coordinate structural constraints
effective-date non-ambiguity
relational cardinality
historical-reference protection
currency/amount structural constraints
schedule/context overlap constraints when feasible
RLS/runtime privilege boundaries
```

Python owns:

```text
semantic command/query validation
policy/context resolution
authorization
transaction framing
option fingerprint semantics
external geocoding orchestration
```

No external I/O under authoritative locks.

---

## 16. Concurrency/race matrix

Before F1 is complete, tests must attempt to falsify at least:

1. price changes after `find_slots` but before `book`;
2. assignment is retired after discovery but before booking;
3. schedule exception is added after discovery but before booking;
4. Location hours change after discovery;
5. OfferingVersion becomes inactive after discovery;
6. concurrent overlapping effective contextual-term writes;
7. concurrent overlapping assignment/schedule writes;
8. configuration mutation concurrent with Booking;
9. existing Reservation remains explainable after price/assignment/schedule changes;
10. existing CapacityClaim provenance cannot be invalidated by config mutation;
11. duplicate display names cannot create authority confusion;
12. timezone/DST boundary does not create duplicate/invalid concrete intervals;
13. cross-tenant guessed IDs remain opaque;
14. contextual booking cannot bypass shared-capacity contention;
15. public contact endpoint mutation cannot cross tenant boundaries.

Booking success always means current contextual state and capacity were revalidated under the accepted transaction protocol.

---

## 17. Backward compatibility

Released V3 already contains Resources, AvailabilitySchedules, ScheduleExceptions, Locations, Offerings, Reservations and Claims.

Compatibility requirements:

```text
existing Resource without contextual assignment
existing Resource schedule
existing Reservation/Claim
existing Location without coordinates
existing OfferingVersion
```

Normative fallback:

```text
accepted contextual configuration exists
  -> use F1 contextual resolution
else
  -> preserve released V3 booking behavior
```

No immediate coordinate backfill is required for legacy Locations not participating in future geospatial discovery.

No migration reinterprets historical Reservations/Claims.

Any required structural backfill must be deterministic and proven on upgrade from `0001_initial`.

---

## 18. Implementation phases

### Phase A — documentation/architecture reconciliation

Completed on the branch at the design-contract level when all of the following are present and mutually consistent:

```text
13-operational-profile-contextual-supply-plan.md
14-operational-intelligence-roadmap.md
15-operational-profile-contextual-supply-contract.md
ADR 0012
docs/README.md precedence
```

Before schema work, perform one final adversarial review against released V3 contracts and existing implementation to ensure the proposed delta is implementable without hidden circular ownership or invariant regression.

### Phase B — implementation inventory

Inspect current:

```text
tenancy Organization model/repos/commands
catalog Location + OfferingVersion persistence/contracts
booking Resource + AvailabilitySchedule + ScheduleException
Reservation persistence
find_slots/book flow
shared-capacity integration
RLS/roles
Alembic migration conventions
```

Produce an exact old->new disposition before writing migration code.

### Phase C — relational schema

Implement the minimal accepted schema in append-only Alembic migration(s).

Prove:

```text
clean bootstrap
upgrade from 0001_initial
repeat bootstrap
schema/catalog assertions
RLS/privilege boundaries
baseline history untouched
```

### Phase D — domain/application model

Add only structures required by real behavior:

```text
domain values/entities
commands
queries
ports
semantic repositories
cross-module contracts
```

Do not create empty architecture folders.

### Phase E — configuration commands

Implement semantic configuration writes with authority/idempotency/revision/audit contracts.

### Phase F — query resolution

Implement deterministic:

```text
business operational info
Location operational info
Resource-at-Location eligibility
schedule composition
contextual price/duration resolution
```

### Phase G — booking integration

Extend `appointments.find_slots` and `appointments.book` without weakening capacity locking.

Close stale-option/config races and persist commercial commitment.

### Phase H — adversarial proof

Run quality/architecture/PostgreSQL/application suites plus new F1 tests.

No merge-readiness claim based only on happy paths.

---

## 19. Required test matrix

### Domain/application

- Organization default validation.
- Location address/timezone/coordinate validation.
- Location public contact endpoint validation.
- Location operational-hours composition.
- Resource assigned to one/multiple Locations.
- Same Resource different schedule by Location.
- Same Resource/Offering different price/duration by Location.
- future effective price.
- schedule exception remove/extend availability.
- distinct Offering/OfferingVersion visit types.
- precedence resolution.
- historical Reservation commercial commitment.

### PostgreSQL/integration

- same-tenant consistency on every new FK/path.
- RLS/role restrictions.
- effective-dated overlap rejection.
- historical-reference immutability.
- clean migration + upgrade from baseline.
- concurrent config changes.
- option-staleness races.
- Booking capacity race under contextual config.
- shared-capacity conflict under contextual booking.

### API/capability

- `business.get_info` returns only safe public operational fields including contact endpoints.
- `catalog` returns version/context-correct information.
- `find_slots` within explicit 13:00-17:00 window.
- `find_slots` with `resource=any` resolves eligible providers.
- option contains correct Location/duration/price.
- `book` rejects stale commercial/schedule/resource context.
- machine-readable errors do not leak foreign tenant information.

### Regression

- released V3 booking still works without contextual config.
- cross-tenant shared-capacity mutex remains intact.
- Queue/waitlist/communications/worker behavior remains unchanged unless touched by an explicit contract.

---

## 20. Acceptance scenarios

### A — operational question answered directly

```text
Cardiologist at Clínica Brugal tomorrow between 1 and 5.
```

RE returns only eligible/available Resources with applicable duration and price.

### B — same physician, different clinics

Correct independent schedules and terms are returned for each Location.

### C — price history

A future price increase does not change an existing confirmed Reservation's historical committed amount.

### D — schedule exception

A one-day exception changes only the targeted day/context and leaves recurrence intact.

### E — stale option

A materially changed option cannot be booked under obsolete assumptions and does not silently change price.

### F — public operational profile

RE can answer Location address, public contact endpoint(s), hours and timezone without Directus.

### G — legacy compatibility

A released-V3 Resource with no contextual assignment preserves baseline booking behavior.

### H — shared-capacity compatibility

A Resource represented across tenants still cannot be double-booked through the new contextual flow.

---

## 21. Definition of Done

F1 is merge-ready only when:

- branch docs/precedence are coherent and reviewed;
- ADR 0012 implementation proof conditions are satisfied;
- new append-only Alembic migration(s) implement only accepted schema;
- `0001_initial`, frozen candidate and V2 design history remain untouched;
- module-first boundaries remain valid;
- no generic operational-config JSONB object is introduced;
- Location public contact endpoints remain narrow/public/tenant-safe;
- Resource-at-Location semantics are explicit and race-safe;
- schedule composition/exceptions are deterministic;
- contextual price/duration resolution is deterministic;
- historical Reservation commercial commitment is immutable/explainable;
- stale option/config races are closed;
- tenant isolation remains intact;
- shared-capacity behavior remains intact;
- clean bootstrap + upgrade + architecture + PostgreSQL + application suites pass;
- adversarial tests cover the race matrix;
- F2–F6 remain documented but unimplemented in this branch.

After F1 merges, the next intended branches are:

```text
feature/geospatial-cross-tenant-discovery
feature/live-service-operations
```

They must branch from the new `development` head and consume, not duplicate, F1 operational truth.