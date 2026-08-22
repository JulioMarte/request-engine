# Operational Profile & Contextual Supply — Feature Plan

Status: active design/implementation plan for `feature/operational-profile-contextual-supply`.

Base: `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573` (post-V3 baseline, after documentation reconciliation PR #74).

Normative F1 contract:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
```

Complete F1–F6 direction:

```text
docs/v3/14-operational-intelligence-roadmap.md
```

Durable rationale:

```text
docs/adr/0012-contextual-resource-location-supply.md
```

The closed F1 clarifications originally recorded in `16-operational-profile-contextual-supply-clarifications.md` are now incorporated into this plan and the normative contract. Document 16 remains adversarial-review/history provenance rather than a permanent higher-precedence layer.

This document defines implementation scope, sequencing, proof obligations and Definition of Done for F1 only. Later cross-tenant discovery, live service operations, workload classification/projection, recovery workflows and the operational copilot remain separate features.

---

## 1. Product objective

Request Engine must own enough structured operational truth to answer and execute:

```text
Can I book a cardiology consultation tomorrow between 1 PM and 5 PM
at Clínica Brugal, with any eligible doctor, and what will it cost?
```

Without requiring CMS/RAG/Memory for operational truth, RE must determine:

```text
Offering + OfferingVersion
Location
eligible Resources
ResourceLocationAssignment eligibility
Location effective hours including exceptions
Resource-at-Location recurring availability
Resource-wide and assignment-specific exceptions
planned duration
fixed applicable amount/currency
current capacity
whether the selected observation is still valid at book time
```

It must also expose the minimum safe public operational profile:

```text
business display/legal operational identity
Organization central public operational contacts
Location address/timezone
Location public operational contacts
Location operational hours
```

Directus remains presentation/content authority. Memory remains learned customer-context authority. Request Engine owns executable operational truth.

---

## 2. F1 scope

### Included

```text
minimal Organization operational profile defaults
Organization central public operational contact endpoints
Location structured address/timezone/status
Location public operational contact endpoints
Location recurring operational hours
Location-hours exceptions / one-off additional hours
normalized Location latitude/longitude
ResourceLocationAssignment effective lifecycle
Resource-at-Location recurring availability
Resource-wide availability exceptions
Resource-at-Location availability exceptions
Offering/OfferingVersion operational-commercial identity
OfferingVersion base commercial terms
contextual Resource + Location + OfferingVersion fixed price/duration
future-effective contextual terms
immutable Reservation commercial commitment + 0..N contextual source provenance
normalized time-window slot queries
aptopt_v2 contextual option observation
stale option/config revalidation
authoritative contextual find_slots -> book flow
legacy V3 booking compatibility
fail-closed contextual hold/reschedule boundary
```

### Explicitly not implemented in F1

```text
cross-tenant marketplace/discovery search
platform-wide discovery token/authority
canonical cross-tenant service taxonomy implementation
popularity ranking
Google reviews / Google Business enrichment
distance/radius marketplace search itself
live queue workload projection
expected/actual live workload classification persistence
same-day adaptive intake closure
ServiceSession execution telemetry
emergency / medical-representative operational activities
patient ETA prediction
end-of-day shortfall recovery
rescheduling campaigns driven by live shortfall
natural-language configuration assistant
EHR/EMR/clinical records
CRM or CMS functionality
route optimization
mobile ServiceArea dispatch
universal pricing engine
machine-learned automatic policy mutation
full contextual CapacityHold lifecycle
full contextual Reservation reschedule replacement
```

`aptopt_v2` contextual hold/reschedule failing closed is an F1 safety contract, not partial implementation of those future commitment flows.

---

## 3. Architectural position

F1 extends the existing modular monolith. It does not create a generic configuration bounded context.

### `tenancy`

Owns:

```text
Organization identity
Principal/Representation authority
minimal operational tenant defaults
Organization central public operational contact endpoints
Party / PartyContactPoint identity remains separate
```

Organization is the tenant/security/administrative boundary and may represent either a clinic or an independent physician/practice.

### `catalog`

Owns:

```text
Location identity/public operational profile
Location structured address/geospatial coordinates
Location public operational contact endpoints
Location recurring operational hours
Location-hours exceptions
Offering
OfferingVersion
ResourceCapability vocabulary
OfferingResourceRequirement
base/default commercial terms
```

### `booking`

Owns:

```text
Resource
ResourceCapability assignment
ResourceLocationAssignment
Resource-at-Location recurring availability
Resource-wide schedule exceptions
Resource-at-Location schedule exceptions
booking-specific contextual terms
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Resource remains the local capacity/serialization root. `CapacityClaim` remains the authoritative capacity-consumption ledger. Assignment/configuration never becomes a second capacity ledger.

---

## 4. Durable model decision

Released V3 intentionally deferred ResourceAssignment until an independently mutable assignment lifecycle was demonstrated. F1 demonstrates it:

```text
one Resource
-> multiple Locations
-> different effective periods
-> different recurring schedules/exceptions
-> different contextual fixed terms
```

F1 therefore introduces `ResourceLocationAssignment`.

Hard rules:

```text
assignment does not consume capacity
assignment cannot cross Organization boundaries
effective overlap for one exact scope cannot be ambiguous
retiring assignment cannot rewrite historical Reservation/Claim provenance
shared-capacity binding still applies to the underlying Resource
legacy wildcard Location eligibility does not reappear after contextual history
```

ADR 0012 remains `Proposed` until the implementation and proof gates are fully closed.

---

## 5. Required domain scenarios

### 5.1 Resource at multiple Locations

```text
Dr. Pérez @ Clínica Brugal
  Tue/Thu 13:00-17:00
  DOP 3,500 / 45m

Dr. Pérez @ Clinic B
  Fri 08:00-12:00
  DOP 4,000 / 30m
```

Contexts never conflate.

### 5.2 Effective Location availability constrains Resource availability

```text
Location recurring hours
APPLY Location-hours exceptions
INTERSECT Resource-at-Location recurrence
APPLY Resource-wide + assignment-specific exceptions
```

Resource additional availability never opens a closed physical Location.

### 5.3 Exception scopes

F1 must distinguish:

```text
"I will not work Monday at Clínica Brugal"
  -> assignment-specific

"I will not work Monday"
  -> Resource-wide
```

A narrow command never silently broadens to other assignments.

### 5.4 Future price change

```text
current = DOP 3,500
from 2026-09-01 = DOP 4,000
```

Fresh options after the effective boundary use current terms. Existing Reservations preserve their committed material commercial truth and source provenance.

### 5.5 Context-only commercial terms

A valid context may be:

```text
no OfferingVersion base amount/currency row
+
exact BookingContextTerms supplies amount/currency
+
OfferingVersion supplies duration
```

This must remain discoverable/bookable and persist its exact contextual source without fabricating a base source.

### 5.6 Commercial Offering identity vs workload classification

`Offering` / `OfferingVersion` is what the business sells/books. A future expected/actual workload classification is an operational observation and may differ from that commercial identity.

F1 may use distinct Offerings when the business truly configures independently meaningful price/duration/eligibility/booking semantics. It must not create a new Offering merely so a future queue predictor can label a visit as a likely quick follow-up/results review.

### 5.7 Normalized time-window query

Natural-language interpretation stays outside Booking. F1 receives explicit timezone-aware windows such as:

```text
2026-08-21 13:00-17:00
```

### 5.8 Public operational contacts

`business.get_info` may expose both:

```text
Organization central phone/WhatsApp/email
Location-specific phone/WhatsApp/email
```

They are different publication relationships and neither grants authority.

---

## 6. Location and geospatial foundation

Location is a physical operational place. Coordinates are optional for legacy/non-geospatial use but, when present:

```text
-90 <= latitude <= 90
-180 <= longitude <= 180
latitude and longitude are both present or both absent
```

Geocoding is ingestion/configuration work and cannot run under authoritative DB locks. F1 does not introduce ServiceArea or require PostGIS without an F2 query/index justification.

---

## 7. Public operational contact endpoints

Organization-level and Location-level public operational endpoints are narrow tenant-owned publication state. Initial channels may include phone, WhatsApp and email.

Required properties:

```text
tenant consistency
normalization appropriate to channel
active/public state
optional narrow operational label/purpose
explicit authority/idempotency/audit on mutation
```

PartyContactPoint remains separate identity/contact state.

---

## 8. Schedule composition

For contextual booking:

```text
Location recurring operational hours
APPLY
Location-hours closures/additional-hours exceptions
=
effective Location availability

INTERSECT
Resource-at-Location recurring availability
APPLY
Resource-wide + assignment-specific exceptions
INTERSECT
explicit contextual temporal eligibility where configured
THEN
capacity revalidation
```

Recurring schedules are local wall-clock rules interpreted through the owning Location IANA timezone. Concrete intervals are timezone-aware and half-open `[start,end)`. DST gaps/folds must be explicitly resolved or rejected; server-local time is never schedule authority.

---

## 9. Contextual commercial terms

F1 supports only deterministic fixed terms:

```text
fixed amount
currency
planned duration
effective dating
OfferingVersion base/default
exact ResourceLocationAssignment + OfferingVersion override
```

Resolution precedence:

```text
exact effective context
>
OfferingVersion base/default
>
missing required term => not quoteable/bookable
```

No formulas, surge pricing, insurance adjudication, coupons, auctions or ML pricing.

---

## 10. Historical Reservation commercial commitment

A contextual Reservation preserves immutable material facts:

```text
amount
currency
planned duration
OfferingVersion
configuration fingerprint
optional base-term source
0..N exact contextual source rows
committed_at/provenance
```

Multi-resource bookings preserve every contributing contextual source; no arbitrary primary context is invented. Historical explanation never depends exclusively on mutable current configuration.

---

## 11. Capability semantics

### `business.get_info`

Returns safe operational identity/defaults, central Organization contacts and Location address/contact/hours/timezone information.

### `catalog.search_offerings` / `catalog.get_offering`

Remain version-aware and respect Offering active state plus effective Location supply. Catalog does not promise concrete capacity.

### `appointments.find_slots`

Returns advisory options for explicit temporal constraints. Contextual options bind Resource choices, assignment/revision observations, Location revision, duration, amount/currency and configuration fingerprint in `aptopt_v2`.

### `appointments.book`

Inside the authoritative transaction revalidate:

```text
tenant/subject authority
Offering parent active state
selected OfferingVersion bookable/versioned state
ResourceLocationAssignment effective state
Location effective availability
Resource recurrence/exceptions
contextual commercial terms
local and shared capacity
```

Success persists Reservation + CapacityClaim assignment provenance + immutable commercial commitment coherently.

### Contextual commitment boundary

F1 supports:

```text
find_slots -> aptopt_v2 -> book
```

Contextual hold/reschedule attempts fail closed before the released V3 commitment adapters. Legacy `aptopt_v1`/released V3 hold/reschedule remains unchanged.

---

## 12. Stale option policy

Material configuration change after discovery causes machine-readable stale/conflict behavior. Booking never silently substitutes a price or overrides current assignment/schedule/Offering authority.

The contextual error surface must direct callers toward refresh-and-retry without leaking foreign-tenant existence.

---

## 13. Authorization

F1 is tenant-scoped. Configuration requires authenticated Principal, Organization context and target-specific Representation/permission.

```text
IDs do not grant authority
foreign guessed IDs remain opaque
request_engine_admin is not normal configuration authority
future assistants call semantic commands, never direct SQL
RLS remains defense-in-depth
```

---

## 14. Semantic command responsibilities

The implemented/public semantic responsibilities are equivalent to:

```text
UpdateOrganizationOperationalProfile
SetOrganizationPublicContacts
CreateLocation
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
explicit Resource-wide schedule exception mutation
ConfigureOfferingVersionBookingTerms
ConfigureBookingContextTerms
```

`ConfigureBookingContextTerms` already supports future effective ranges, so a duplicate scheduling command is unnecessary.

Every retryable mutation defines idempotency, authority, revision/stale-intent rules where relevant, transaction boundary, invariants, machine-readable failures and audit provenance.

---

## 15. PostgreSQL and migration rules

F1 is append-only post-V3 evolution:

```text
DO NOT edit migrations/versions/0001_initial.py
DO NOT append F1 product changes to migrations/sql/v3_candidate/
DO NOT mutate migrations/sql/design_chain/ history
```

The still-unshipped F1 schema is consolidated into:

```text
0002_f1_supply
```

PostgreSQL backstops tenant consistency, relational/cardinality constraints, effective-date non-ambiguity, immutable provenance, structural commercial/coordinate constraints, RLS/runtime privileges and capacity guards. Python owns semantic orchestration, authority, option/fingerprint policy and external geocoding orchestration.

---

## 16. Concurrency/race matrix

Before F1 is complete, proof must attempt to falsify:

1. price/context change after discovery before book;
2. assignment retirement after discovery;
3. assignment-specific exception vs book;
4. Resource-wide exception vs book;
5. Location-hours exception vs book;
6. recurring Location-hours mutation vs book;
7. parent Offering deactivation vs book;
8. concurrent overlapping contextual-term writes;
9. concurrent overlapping assignment writes;
10. concurrent schedule replacement/stale revision;
11. existing Reservation/CapacityClaim provenance after later config mutation;
12. duplicate human-readable names as an authority confusion vector;
13. DST gap/fold behavior;
14. foreign guessed IDs across new read/write surfaces;
15. contextual shared-capacity contention;
16. Organization/Location contact mutation cross-tenant attempts;
17. context-only price with no base terms;
18. multi-source commercial provenance;
19. contextual hold/reschedule fall-through into legacy V3 handlers.

Booking success always means current contextual state and capacity were revalidated under the accepted protocol.

---

## 17. Backward compatibility

Legacy Resources that never enter contextual assignment history preserve released V3 scheduling/Location behavior. Contextual history prevents accidental restoration of a legacy wildcard Location interpretation after assignment retirement.

Existing Reservations/Claims are never rewritten. Released V3 `aptopt_v1` booking/hold/reschedule paths remain compatible. Contextual choices use the contextual direct-book path and fail closed for unsupported hold/reschedule operations.

---

## 18. Implementation phases

### Phase A — documentation/architecture reconciliation

Maintain one coherent normative F1 contract/plan and preserve roadmap/ADR rationale.

### Phase B — implementation inventory

Completed old->new disposition before SQL. The historical inventory remains in document 17.

### Phase C — relational schema

Consolidated post-baseline `0002_f1_supply` implements the accepted relational model and ACL/RLS hardening.

### Phase D — domain/application model

Implemented only structures required by actual behavior; no generic configuration bounded context.

### Phase E — semantic configuration commands

Implemented authority/idempotency/revision/audit surfaces including CreateLocation and Organization public contacts.

### Phase F — query resolution

Implemented business operational info, catalog Location/effective-supply filtering, deterministic schedule composition and contextual terms.

### Phase G — booking integration

Implemented contextual `find_slots -> aptopt_v2 -> book`, stale observation checks, commercial commitment and shared-capacity compatibility. Contextual hold/reschedule intentionally fail closed for F1.

### Phase H — adversarial proof and merge-readiness

Complete the matrix in section 16, public capability flow, canonical CI, documentation reconciliation and ADR acceptance decision. No happy-path-only merge claim.

---

## 19. Required test matrix

### Domain/application

- Organization/default/contact validation.
- Location address/timezone/coordinate validation.
- Location recurring hours plus Location-hours exceptions.
- Resource-wide vs assignment-specific exception scope.
- Resource assigned to one/multiple Locations.
- Same Resource different schedule/terms by Location.
- future effective terms.
- commercial precedence including context-only price.
- multi-source historical commercial provenance.

### PostgreSQL/integration

- same-tenant consistency on every new FK/path.
- RLS/runtime role restrictions.
- effective overlap rejection including concurrent writers.
- historical-reference immutability.
- clean bootstrap + upgrade from baseline.
- config-vs-book races.
- DST gap/fold behavior.
- duplicate-name authority safety.
- shared-capacity contention.

### API/capability

- `business.get_info` exposes only safe Organization/Location operational fields.
- catalog Location/effective-supply behavior.
- explicit-window `find_slots` with any eligible Resource.
- `aptopt_v2` round-trip preserves contextual observations.
- decoded contextual option books successfully.
- stale option maps to machine-readable refresh-and-retry.
- foreign guessed IDs remain opaque.
- contextual hold/reschedule fails closed before legacy handlers.

### Regression

- released V3 booking remains green without contextual config.
- released V3 `aptopt_v1` reschedule/commitment path remains valid.
- cross-tenant shared-capacity mutex remains intact.
- Queue/waitlist/communications/worker behavior remains unchanged unless explicitly touched.

---

## 20. Acceptance scenarios

### A — operational question answered directly

RE returns only eligible/available Resources at the requested Location/window with applicable duration and price.

### B — same Resource, different Locations

Schedules and terms remain independent.

### C — price history

Future terms do not rewrite existing Reservation commercial truth.

### D — exceptions

Location, Resource-wide and assignment-specific exceptions alter only their explicit scope without rewriting recurrence.

### E — stale option

Materially changed observations cannot book under obsolete assumptions and map to refresh-and-retry.

### F — public operational profile

RE returns Organization central contacts plus Location address/contacts/hours/timezone without Directus.

### G — legacy compatibility

Released V3 non-contextual behavior remains intact.

### H — shared capacity

A globally bound Resource cannot be double-booked through contextual supply.

### I — contextual capability flow

`business.get_info -> catalog -> find_slots -> aptopt_v2 -> book` succeeds coherently and persists exact commercial/assignment provenance.

### J — commitment boundary

Contextual hold/reschedule fails closed before legacy handlers while `aptopt_v1` reschedule still reaches the released handler.

---

## 21. Definition of Done

F1 is merge-ready only when:

- branch documentation is coherent and document 16 is no longer required as a live precedence layer;
- ADR 0012 implementation proof conditions are satisfied and its final status is decided only after proof;
- `0002_f1_supply` implements only accepted post-baseline schema;
- `0001_initial`, frozen V3 candidate and V2 design history remain untouched;
- module-first boundaries remain valid and no generic operational-config JSONB is introduced;
- Organization and Location public endpoints remain narrow, public, tenant-safe and separately owned;
- ResourceLocationAssignment semantics and broad/narrow exception scopes are explicit and race-safe;
- schedule/timezone composition is deterministic including DST safety;
- contextual price/duration resolution is deterministic including context-only and multi-source provenance cases;
- historical Reservation/CapacityClaim/commercial provenance is immutable/explainable;
- stale option/config races are closed, including Offering parent deactivation;
- contextual hold/reschedule is proven fail-closed before legacy commitment code and legacy V3 behavior remains green;
- tenant isolation and foreign-ID opacity remain intact across new surfaces;
- shared-capacity behavior remains intact;
- API/capability flow proves `business -> catalog -> find_slots -> aptopt_v2 -> book`;
- clean bootstrap + upgrade + architecture + PostgreSQL + application + frozen-V3 compatibility jobs pass at the same exact head;
- F2–F6 remain documented but unimplemented in this branch.

After F1 merges, the next intended work consumes this operational truth rather than duplicating it.