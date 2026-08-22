# Request Engine — Operational Profile & Contextual Supply Contract

Status: normative for `feature/operational-profile-contextual-supply`; becomes accepted post-V3 contract only when the feature is proven and merged.

Base: released V3 baseline plus `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573`.

This document is the post-V3 normative delta for F1. It does not erase or reinterpret the released V3 baseline. Where this document explicitly extends or conflicts with the following baseline sections for F1 concepts, this document wins on this branch:

```text
docs/v3/01-capability-contracts.md
  business.get_info
  catalog search/details operational fields
  appointments.find_slots option semantics
  appointments.book commercial/context revalidation

docs/v3/02-pre-sql-contract.md
  Location operational fields
  Resource availability scoping
  AvailabilitySchedule / ScheduleException scope
  Reservation commercial provenance
  post-baseline ResourceAssignment decision

docs/10-module-ownership-map.md
  operational-profile/contextual-supply ownership described below
```

All unrelated V3 invariants, transaction rules, tenant isolation, shared-capacity behavior, queue semantics, communications boundaries and migration history remain in force.

---

## 1. Product promise

Request Engine must be able to answer from operational truth alone:

```text
Can I book cardiology at Clínica Brugal tomorrow between 1 PM and 5 PM,
with any eligible doctor, and what will it cost?
```

For a concrete appointment option RE must be able to resolve:

```text
OfferingVersion
Location
eligible Resource set
Resource-at-Location availability
Location operational hours
applicable exceptions
planned duration
committed/bookable price and currency
current capacity
```

Directus/CMS, RAG and learned Memory are not required to determine those operational facts.

---

## 2. Explicit product boundary

F1 owns structured facts necessary to execute operations. It does not become a CMS, CRM, EHR or universal pricing engine.

Examples that belong in RE:

```text
business display/legal identity needed operationally
Organization central public operational contact endpoints
Location address and public operational contact endpoints
Location timezone/hours
Location coordinates
Offering/OfferingVersion
doctor/resource capability
where a Resource works
when a Resource works there
bookable price/duration in that context
schedule exceptions
```

Examples outside F1 authority:

```text
long physician biography
SEO content
images
marketing FAQ
clinical notes
diagnosis
medication
Google review text
learned customer preference
```

---

## 3. Module ownership

No generic `configuration` bounded context is introduced.

### 3.1 `tenancy`

Owns:

```text
Organization
Principal
Party / PartyContactPoint identity
Representation / delegated authority
minimal Organization operational defaults
Organization public operational contact endpoints
```

Organization operational defaults may include:

```text
legal_name
public/display_name
default_timezone
default_locale
default_currency
status
```

Organization public operational contact endpoints are business-level publication state such as a central appointment phone, WhatsApp or email. They are not Party/customer contact identity and do not grant authority.

These are typed fields/value objects. Do not introduce an unbounded `operational_config JSONB` object.

### 3.2 `catalog`

Owns:

```text
Location identity and public operational profile
Location operational hours
Location-hours exceptions
Location public operational contact endpoints
Location geospatial coordinates
Offering
OfferingVersion
ResourceCapability vocabulary
OfferingResourceRequirement
base/default commercial terms attached to OfferingVersion
```

`Location` remains catalog/business configuration, not a Resource identity.

Public Location contact endpoints are operational contact data, not a CRM/person profile. `PartyContactPoint` remains tenancy-owned identity/contact state for Parties; do not silently conflate the two lifecycles.

### 3.3 `booking`

Owns:

```text
Resource
ResourceCapability assignment
Resource-at-Location assignment
Resource-at-Location recurring availability
Resource-wide schedule exceptions
Resource-at-Location schedule exceptions
booking-specific Resource/Location/Offering context
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

The booking-specific contextual record may carry narrow commercial overrides required to quote/book an appointment, including resource/location-specific price and planned duration. This is allowed because the demonstrated requirement is specifically concrete booking supply. It must not evolve into a generic pricing language.

If pricing later becomes a shared independent lifecycle across non-booking capabilities, that is evidence for a separate accepted pricing boundary; F1 must not anticipate it.

---

## 4. Core entities and cardinalities

Names below are conceptual contracts. Persisted names may differ only if semantics remain explicit and documentation/tests use one canonical term.

### 4.1 Organization operational profile

```text
Organization 1 -- 0..1 operational profile/default set
```

The implementation may store these fields directly on Organization or in a 1:1 typed relation if migration/ownership considerations justify it.

No arbitrary metadata bag substitutes for typed fields.

An Organization is the tenant/security/administrative boundary; it is not synonymous with a clinic. A valid Organization may represent a multi-physician clinic or an independent physician/practice.

### 4.2 Location

A Location is one physical operational place owned by one Organization.

Conceptual fields:

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

Coordinate rules:

```text
-90 <= latitude <= 90
-180 <= longitude <= 180
latitude and longitude are both present or both absent
```

A Location must have usable coordinates before participating in future distance-based discovery. Legacy/non-discovery Locations may remain without coordinates in F1.

### 4.3 Location public operational contact endpoint

A Location may expose `0..N` public operational contact endpoints.

Conceptual kinds may include:

```text
phone
whatsapp
email
other explicitly supported channel
```

Required semantics:

```text
same Organization as Location
typed/normalized value
public/active state
purpose/label only where operationally needed
```

Possession of a contact endpoint never grants authority.

This is not a generic CRM contact book.

### 4.4 Location operational hours

A Location may have one or more recurring local operational-hour windows.

They describe when the physical Location can normally support operations.

They are interpreted in the Location IANA timezone.

F1 booking options at a physical Location must not extend outside applicable Location operational hours unless an explicit effective Location-hours exception/additional-hours rule makes that time operationally valid.

Recurring Location hours and one-off Location-hours exceptions are different facts. Holiday closure, early close, one-off opening and one-day extended hours are expressed through explicit Location-scoped exceptions rather than by creating one Resource exception per physician.

### 4.5 Resource-at-Location assignment

The released V3 baseline deferred `ResourceAssignment` because no independent assignment lifecycle had been proven. F1 provides that evidence.

A Resource can work at multiple Locations with independently mutable effective periods and schedules:

```text
Resource N -- M Location
```

represented through an explicit assignment concept, provisionally named:

```text
ResourceLocationAssignment
```

Minimum semantics:

```text
organization_id
resource_id
location_id
effective_from
effective_until?
status/revision
```

Validity uses half-open effective intervals:

```text
[effective_from, effective_until)
```

where an absent `effective_until` means open-ended.

An active/effective assignment proves only that the Resource may operate at that Location. It does not consume capacity and is not a second CapacityClaim ledger.

For the same Resource + Location, simultaneously active/effective assignment rows must not create ambiguous overlapping configuration. The accepted schema must enforce or transactionally prevent overlap.

### 4.6 Resource-at-Location availability

Recurring Resource availability is scoped to the operational context where it applies.

F1 must not retain one ambiguous global `Resource.schedule` if the Resource works different schedules at different Locations.

Conceptually:

```text
ResourceLocationAssignment 1 -- 0..N recurring availability windows
```

A legacy Resource without contextual assignment may continue using released V3 Resource availability under the backward-compatibility rule in section 14.

### 4.7 Commercial Offering identity and live workload classification

F1 does **not** introduce a parallel universal `VisitVariant` lifecycle merely because users say “new consultation”, “follow-up” or “results review”.

`Offering` / `OfferingVersion` is the versioned operational-commercial service the business sells or books. It is not required to be the same identity as a future live-workload classification used to estimate how a service is likely to behave operationally.

When the business genuinely sells/configures distinct services with materially different price, planned duration, eligibility or booking semantics, they may be represented as distinct Offerings/OfferingVersions, for example:

```text
Cardiology - New Consultation
Cardiology - Follow-up
```

But F1 must not create or rewrite an Offering merely because a future operational observer predicts that an appointment is likely to be a quick results review. A later feature may record expected/actual workload classification without rewriting the booked OfferingVersion.

### 4.8 Booking contextual terms

A concrete bookable context is conceptually:

```text
OfferingVersion
x ResourceLocationAssignment
x effective time
```

A booking-context configuration may specify narrow overrides such as:

```text
price amount/currency
planned duration
bookable/active state
booking-policy reference where an accepted policy requires context
```

Default resolution order for F1 is explicit:

```text
1. exact Resource + Location + OfferingVersion effective booking context
2. OfferingVersion base/default term
3. missing required term => not quoteable/bookable under the capability that requires it
```

Do not add hidden multi-level inheritance beyond these accepted levels.

Contextual configuration validity is effective-dated with non-ambiguous overlap rules for one exact scope.

---

## 5. Price and planned duration

### 5.1 Narrow pricing semantics

F1 supports:

```text
fixed amount
currency
effective dating
OfferingVersion default
Resource + Location contextual override
```

F1 does not support:

```text
arbitrary formulas
surge pricing
insurance adjudication
coupon engine
auction
ML pricing
complex tax engine
```

### 5.2 Historical commercial commitment

A successful appointment booking must persist enough immutable commercial provenance to explain later what the patient/customer agreed to.

At minimum the Reservation or an immutable Reservation-owned commercial record preserves:

```text
committed amount
currency
OfferingVersion reference
resolved booking-context reference/revision or equivalent provenance
committed_at / booking transaction provenance as needed
```

A later price edit must never change the historical amount of an existing confirmed Reservation.

Historical explanation must not depend exclusively on joining through mutable current configuration.

### 5.3 Price/config race between discovery and booking

`appointments.find_slots` is advisory.

An AppointmentOption produced under F1 must carry or bind an opaque server-verifiable observation of the relevant contextual configuration, sufficient to detect stale commercial/schedule assumptions.

Normative F1 behavior:

> `appointments.book` never silently substitutes a materially different price for the price presented in the selected option.

If the applicable price/context changed after option discovery, booking returns a machine-readable stale/conflict response and directs the caller to obtain fresh options.

A future explicit “accept latest price” capability could be designed separately; it is not implicit F1 behavior.

---

## 6. Schedule composition

For contextual Resources the final candidate interval is valid only if all applicable constraints agree.

Conceptual composition:

```text
Location recurring operational hours
APPLY
Location-level closures/additional-hours exceptions
=
effective Location operational availability

then

effective Location operational availability
INTERSECT
Resource-at-Location recurring availability
APPLY
applicable Resource-wide + assignment-specific exceptions
INTERSECT
OfferingVersion/context temporal eligibility when explicitly configured
THEN
capacity revalidation against Holds/Claims/Reservations
```

### 6.1 No implicit Organization-hours inheritance

Organization may expose general business hours for information, but multi-location booking must not silently apply one Organization schedule to every Location.

A physical booking is constrained by its effective Location operational availability.

### 6.2 Resource-wide and Resource-at-Location exceptions are distinct intents

F1 distinguishes:

```text
Resource-at-Location exception
  -> affects one explicit ResourceLocationAssignment/context

Resource-wide exception
  -> affects the Resource across all applicable Location assignments
```

A command targeting one ResourceLocationAssignment must never silently broaden to unrelated assignments. A Resource-wide exception must be explicit and auditable.

Examples include:

```text
closed/unavailable for a date/range
shortened day
additional availability
block 12:00-13:00
extend one day until 19:00
```

An exception does not rewrite the recurring schedule.

Resource additional availability cannot make a physical Location bookable while effective Location operational availability is closed.

### 6.3 Time semantics

Recurring schedules are local wall-clock rules interpreted through the owning Location timezone.

Authoritative concrete intervals use timezone-aware instants and half-open `[start,end)` semantics.

Ambiguous/nonexistent DST local times must be explicitly resolved or rejected. The fact that the initial Dominican target has no DST does not permit server-local implicit conversion.

---

## 7. Public/application capabilities

### 7.1 `business.get_info`

May return public structured operational information such as:

```text
Organization display name
public Organization defaults
Organization central public operational contact endpoints
Locations
Location structured address
Location public contact endpoints
Location operational hours and effective exceptions
Location timezone
```

Organization-level and Location-level contact endpoints are distinct publication surfaces; neither silently overrides the other.

Coordinates may be returned only when the public contract/policy permits them. F1 does not expose private authority/admin metadata.

### 7.2 `catalog.search_offerings`

May filter by:

```text
text/category
Location
active/effective time
```

and return structured Offering/OfferingVersion information sufficient to identify bookable service types.

It does not promise concrete capacity until booking availability is resolved.

### 7.3 `catalog.get_offering`

Returns version-aware structured operational/commercial defaults and the allowed Location/context hints that are safe for the caller.

### 7.4 `appointments.find_slots`

Input extends the released V3 capability with contextual resolution:

```text
offering_id / OfferingVersion selection
subject when eligibility requires it
location_id?
normalized date/time window
presentation timezone
optional Resource/provider preference, including any eligible Resource
```

Natural-language phrases such as:

```text
tomorrow afternoon
between 1 and 5
after 2
```

are normalized by the caller/agent layer into explicit temporal constraints before entering booking. Booking does not parse arbitrary natural language.

An F1 AppointmentOption may include:

```text
opaque option token/id
OfferingVersion
Resource/provider display info when policy allows
Location
start_at
end_at
planned duration
applicable amount
currency
presentation timezone
staleness/config observation bound into the opaque option
```

`find_slots` creates no capacity commitment.

### 7.5 `appointments.book`

Booking revalidates inside the authoritative transaction:

```text
Organization/authority
Offering active state + selected OfferingVersion bookable state
ResourceLocationAssignment effective state
Location operational hours/exceptions
Resource-at-Location schedule
Resource-wide and assignment-specific exceptions
contextual terms / price observation
Resource capacity
shared-capacity roots when the Resource is globally bound
```

Success means capacity and historical Reservation commercial commitment are persisted coherently.

Failure leaves no partial Reservation/claim/commercial commitment.

### 7.6 Contextual hold/reschedule scope for F1

F1 explicitly supports the contextual commitment path required by its product promise:

```text
appointments.find_slots -> aptopt_v2 -> appointments.book
```

F1 does **not** implement contextual `CapacityHold` or contextual Reservation reschedule replacement flows. Passing an `aptopt_v2`/contextual `ResourceChoice` into those released-V3 commitment paths must fail closed with a machine-readable `contextual_commitment_unsupported` result **before** a legacy adapter can drop assignment/schedule/commercial provenance.

Released-V3 `aptopt_v1` hold/reschedule behavior remains compatible and continues through the legacy path.

This fail-closed behavior is an accepted F1 scope decision, not an unfinished requirement. A future feature may add contextual hold/reschedule only by reusing the same assignment, schedule, commercial, stale-option and capacity revalidation semantics as contextual booking.

---

## 8. Authorization

F1 remains tenant-scoped.

It does not implement platform-wide cross-tenant discovery authority.

All configuration commands require:

```text
authenticated Principal
Organization tenant context
specific Representation/permission appropriate to the target
```

Possession of Organization, Resource, Location, Offering or assignment IDs never grants authority.

`request_engine_admin` is not the normal path for physician/clinic operational configuration.

A physician-specific command may be authorized only for Resources/scopes the Principal is allowed to manage. A clinic admin may have broader tenant authority. Exact permissions are introduced with concrete commands, not through a speculative universal RBAC product.

A future natural-language assistant receives no special database authority; it calls these same semantic commands.

RLS/tenant context remains defense-in-depth and new relations must prove tenant consistency.

---

## 9. Configuration commands

Final API names may change, but F1 must expose semantic command responsibilities equivalent to:

```text
UpdateOrganizationOperationalProfile
SetOrganizationPublicContactEndpoint(s)
CreateLocation / UpdateLocationOperationalInfo
SetLocationOperationalHours
Create/Change/retire LocationHoursException
SetLocationPublicContactEndpoint(s)
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
Create/Change ResourceLocationAvailabilityException
Create/Change explicit Resource-wide AvailabilityException
ConfigureBookingContextTerms
ScheduleFutureBookingContextTerms
```

`ConfigureBookingContextTerms` may satisfy both immediate and future-effective contextual-term responsibilities when its effective-dating contract is explicit; a duplicate command name is not required merely to represent a future boundary.

Every network/agent-retryable mutation defines:

```text
idempotency semantics
authority
expected revision/stale-intent behavior where relevant
transaction boundary
invariants
machine-readable errors
audit provenance
```

No direct generic CRUD endpoint is the authoritative business contract.

---

## 10. Transaction and serialization rules

### 10.1 Configuration writes

Mutations that change a Resource's effective bookability must serialize through an accepted Resource/assignment configuration root and advance a revision/fingerprint observable by option generation.

The exact SQL lock topology is finalized with schema implementation, but it must prevent concurrent writes from committing ambiguous overlapping active configuration.

### 10.2 Booking

The existing V3 booking lock/capacity protocol remains authoritative.

For a contextual Resource, booking additionally revalidates the current assignment/schedule/context before creating claims.

Context configuration is not a capacity ledger. `CapacityClaim` remains the authoritative local capacity-consumption truth.

Existing cross-tenant shared-capacity locking remains additive for bound Resources and must not be bypassed by contextual assignment.

### 10.3 No external I/O under locks

Geocoding and any future provider lookup occur outside authoritative lock-held transactions.

---

## 11. Required invariants

The implementation/schema must make the following false states impossible or rejected through the supported transaction protocol:

1. A ResourceLocationAssignment crosses Organizations.
2. A contextual Offering reference crosses Organizations.
3. Two effective configurations for the same exact scope ambiguously apply at the same instant.
4. Resource-at-Location availability exists for a foreign/unrelated assignment.
5. A Location contact endpoint, operational-hours row or Location-hours exception belongs to a different Organization than its Location.
6. Organization public operational contacts cross their Organization boundary or grant Party authority.
7. A Resource-at-Location exception silently affects another assignment.
8. A Resource-wide exception is inferred from an assignment-scoped mutation instead of being explicit.
9. A confirmed Reservation's committed price/currency can be rewritten by later configuration changes.
10. Retiring an assignment destroys or changes the historical meaning of an existing Reservation/CapacityClaim.
11. Booking succeeds against a Resource assignment that became inactive before the authoritative booking transaction.
12. Booking succeeds after its parent Offering became inactive or outside current Location/resource schedule after a stale option.
13. Booking silently changes a presented material price.
14. Coordinate latitude/longitude values are structurally invalid or only one coordinate is present.
15. A guessed foreign tenant ID becomes an existence oracle through new contextual queries/errors beyond accepted opaque semantics.
16. New contextual configuration bypasses the existing shared-capacity mutex for a globally bound Resource.
17. A contextual hold/reschedule silently falls through to a released-V3 adapter that cannot preserve contextual provenance.

---

## 12. Race matrix

At minimum tests must falsify:

```text
price changes after find_slots before book
assignment retired after find_slots before book
assignment-specific schedule exception added after find_slots before book
Resource-wide exception added after find_slots before book
Location-hours exception added after find_slots before book
recurring Location hours changed after find_slots before book
parent Offering deactivated after find_slots before book
concurrent overlapping effective-term writes
concurrent overlapping assignment/schedule writes
configuration mutation concurrent with booking
legacy booking concurrent with new contextual booking
shared-capacity contention using a contextual Resource
duplicate human-readable names do not grant authority
DST gap/fold local times are explicitly rejected/resolved
foreign-tenant guessed IDs remain opaque
Organization/Location public-contact mutation remains tenant-local
```

Expected outcome for stale discovery/configuration is an opaque machine-readable stale/unavailable/conflict result, never partial state or silent commercial substitution.

---

## 13. Historical provenance

Configuration lifecycle is mutable/effective-dated, but material transaction history is not reconstructed from mutable current rows alone.

A Reservation must remain explainable after:

```text
future price change
assignment retirement
schedule change
Location-hours change
Resource moved to another Location
Offering later deactivated
```

No supported configuration command may retarget historical Reservation/CapacityClaim provenance to make old facts appear to have used new configuration.

---

## 14. Backward compatibility

Released V3 Resources may exist with:

```text
Resource-scoped AvailabilitySchedule
Resource ScheduleException
Location eligibility
no ResourceLocationAssignment
no coordinates
no committed-price fields introduced by F1
```

F1 migration must preserve existing semantics for legacy rows unless they are explicitly migrated into contextual configuration.

Normative compatibility rule:

```text
if accepted contextual Resource-at-Location configuration exists
  -> use F1 contextual resolution
else
  -> preserve released V3 tenant-local booking behavior
```

Do not require immediate coordinate backfill for legacy Locations that do not participate in geospatial discovery.

Existing Reservations/Claims are never reinterpreted to invent historical price/context provenance they did not record at creation time.

Any backfill required for new non-null structural fields must be deterministic, migration-safe and separately proven on upgrade from `0001_initial`.

---

## 15. Migration strategy

This feature is post-V3 production evolution.

Non-negotiable:

```text
do not edit migrations/versions/0001_initial.py
do not append product changes to migrations/sql/v3_candidate/
do not mutate migrations/sql/design_chain/ history
```

F1 schema changes use new append-only Alembic revision(s) after the released baseline.

CI/evidence must prove:

```text
clean bootstrap
upgrade from 0001_initial
repeat bootstrap
schema/catalog assertions
runtime role/RLS/privilege boundaries
existing V3 tests
new F1 adversarial tests
```

---

## 16. Explicit non-goals

F1 does not implement:

```text
cross-tenant discovery
platform discovery service token
popularity ranking
Google Business/reviews
live ServiceSession telemetry
queue ETA
same-day adaptive intake
emergency/visitor operational timeline
end-of-day recovery communications
natural-language operational copilot
ServiceArea/mobile dispatch
route optimization
universal pricing engine
EHR/clinical records
contextual CapacityHold/reschedule replacement flows
```

Those are preserved in `docs/v3/14-operational-intelligence-roadmap.md` and require separate features where applicable.

---

## 17. Acceptance

F1 is not complete until the following examples are proven:

### A — contextual search

```text
Cardiology at Clínica Brugal tomorrow between 13:00 and 17:00, any eligible doctor.
```

Only Resources genuinely available at that Location/time appear, with applicable duration and price.

### B — same physician, different clinic

Dr. Pérez may be:

```text
Brugal Tue/Thu 13:00-17:00, DOP 3,500 / 45m
Clinic B Fri 08:00-12:00, DOP 4,000 / 30m
```

The contexts never conflate.

### C — future price

A DOP 3,500 appointment booked before an effective change remains DOP 3,500 historically; fresh options after the effective boundary show DOP 4,000.

### D — one-day exception

An exception shortens or extends one day's Resource-at-Location schedule without rewriting recurring weeks.

### E — stale option

A selected option whose price/schedule/assignment changed before booking is rejected as stale/unavailable rather than booked under obsolete or silently substituted terms.

### F — public operational info

`business.get_info` can return Organization central public contacts plus Location address, hours and Location-specific public operational contact endpoint(s) without querying Directus.

### G — legacy regression

A released-V3 Resource without new contextual configuration retains its existing booking behavior, including `aptopt_v1` commitment flows.

### H — shared-capacity regression

A Resource bound to cross-tenant shared capacity remains protected against overlapping commitments even when booked through new Resource-at-Location contextual supply.

### I — contextual commitment boundary

A contextual `aptopt_v2` can be booked through the authoritative contextual path, while contextual hold/reschedule fails closed and the released `aptopt_v1` reschedule path remains valid.