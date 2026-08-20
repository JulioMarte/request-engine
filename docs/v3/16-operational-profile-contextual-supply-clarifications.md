# Request Engine — Operational Profile & Contextual Supply Clarifications

Status: normative clarification/amendment for `feature/operational-profile-contextual-supply`.

This document records the findings of the second adversarial documentation audit performed after `13-operational-profile-contextual-supply-plan.md`, `14-operational-intelligence-roadmap.md`, `15-operational-profile-contextual-supply-contract.md` and ADR 0012 were written.

Its purpose is not to add implementation scope casually. It corrects places where the previous documents either closed a decision more strongly than the product discussion justified or left operational semantics ambiguous.

Until these clarifications are consolidated into the main F1 contract before merge, this document has precedence over the specific sections named below.

It supersedes only:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
  4.7 Offering variants
  6.2 Exceptions
  7.1 business.get_info only where Organization-level public contact is discussed
  9 Configuration commands only for the additional exception/contact responsibilities below
  11 Required invariants only where the additional exception scopes below strengthen them

docs/v3/13-operational-profile-contextual-supply-plan.md
  5.6 Operational visit types
  8 Schedule composition/exception semantics where clarified below
  candidate command/test/acceptance lists where clarified below

docs/v3/14-operational-intelligence-roadmap.md
  F2 tenant-participant assumptions and canonical cross-tenant classification requirement
  F3 expected/actual workload classification relationship to F1 Offerings
  F3 interruption authority direction
```

All other rules in the F1 contract, plan, roadmap, ADR 0012 and released V3 baseline remain in force.

---

## 1. Commercial Offering identity is not the same as live workload classification

The earlier F1 contract closed this too strongly by saying that operational visit types such as:

```text
new consultation
follow-up
results review
procedure
```

should be represented as distinct `Offering` / `OfferingVersion` whenever they have independently meaningful price, planned duration or booking semantics.

That is a valid modeling option for genuinely distinct commercial services, but it is **not** the universal rule for operational classification.

The accepted distinction is now:

```text
Offering / OfferingVersion
  = what the business sells/books as a versioned operational-commercial service

Expected workload classification
  = what staff/system currently expects the live service to resemble for operational timing/projection

Actual service classification
  = what the delivered live service was operationally classified as after/during execution
```

These concepts may coincide, but they are not required to be the same identity.

### 1.1 F1 rule

F1 continues to use `Offering` / `OfferingVersion` for commercial/booking identity.

If the business truly sells and configures separately:

```text
Cardiology - New Consultation
Cardiology - Follow-up
```

with materially different price, duration, eligibility or booking semantics, those **may** be separate Offerings/OfferingVersions using existing lifecycle/versioning.

But F1 must not force an operational observation such as:

```text
"this patient is probably only coming for a quick results review"
```

into a new Offering merely so a future queue predictor can estimate workload.

### 1.2 F3/F4 direction

F3 may introduce a narrow tenant/Offering-aware operational classification vocabulary or fact capable of recording:

```text
expected_workload_class
actual_workload_class
```

without rewriting the booked OfferingVersion.

Example:

```text
booked OfferingVersion = Cardiology Consultation
expected workload      = results_review
actual workload        = full_consultation
```

The historical expected classification must not be rewritten later just because the actual service differed.

The exact persisted F3 concept is intentionally not fixed in F1.

### 1.3 Projection rule

F4 may use the expected classification to estimate remaining workload, but classification does not change queue order by itself and does not change commercial truth automatically.

---

## 2. Location recurring hours require Location-level exceptions

F1 must support both recurring Location hours and exceptional Location availability.

A recurring weekly schedule cannot safely represent cases such as:

```text
clinic closed for a holiday
clinic closes early today
clinic opens exceptionally on Sunday
one-off building/utility closure
one-day extended hours
```

Creating one Resource exception per physician is not an acceptable substitute for a Location-wide operational fact.

### 2.1 Required semantic model

Conceptually:

```text
LocationOperationalHours
+
LocationHoursException
```

The persisted names may differ, but the lifecycle must support a Location-scoped effective exception/additional-hours fact.

A Location exception may:

```text
close a date/range
shorten a day
block a sub-range
add one-off availability
extend one day
```

It does not rewrite the recurring Location schedule.

### 2.2 Composition

For physical booking, resolve effective Location availability first:

```text
Location recurring operational hours
APPLY
Location-level closures/additional-hours exceptions
=
effective Location operational availability
```

Then compose:

```text
effective Location operational availability
INTERSECT
Resource-at-Location recurring availability
APPLY
applicable Resource exception scope
INTERSECT
explicit Offering/context temporal restrictions when configured
THEN
capacity revalidation
```

A Resource exception can never make the physical Location bookable while an effective Location closure forbids operation, unless a trusted command also explicitly changes the Location operational state.

### 2.3 Required command responsibilities

F1 must include semantic responsibilities equivalent to:

```text
SetLocationOperationalHours
CreateLocationHoursException
ChangeLocationHoursException
Cancel/retire LocationHoursException when applicable
```

Naming may be refined during implementation.

### 2.4 Required invariants

At minimum:

```text
Location-hours exception belongs to same Organization as Location
ambiguous overlapping effective exception state for the same exact scope is rejected
foreign tenant Location IDs cannot be used as an existence oracle
stale AppointmentOptions are revalidated against current effective Location availability
```

### 2.5 Required tests

Add adversarial tests for:

```text
holiday closure after find_slots before book
one-day early close
one-day extended Location hours
concurrent conflicting Location-hours exceptions
Resource additional availability while Location remains closed
legacy Location without exception rows
```

---

## 3. Resource-wide exceptions and Resource-at-Location exceptions are different intents

F1 must distinguish two real user intents:

```text
"I will not work next Monday at Clínica Brugal."
```

versus:

```text
"I will not work next Monday."
```

For a Resource assigned to multiple Locations, the first is context-specific and the second is Resource-wide.

### 3.1 Required semantics

F1 must be able to express:

```text
Resource-at-Location exception
  affects one explicit assignment/context

Resource-wide availability exception
  affects the Resource across all applicable Location assignments in its explicit effective scope
```

The exact physical schema may use separate rows/tables or one typed exception model with explicit scope. What is not allowed is implicit broadening based on convenience.

### 3.2 Safety rule

A command targeting one ResourceLocationAssignment must never silently affect another assignment.

A Resource-wide command must be explicit and auditable.

For example, a semantic command may be equivalent to:

```text
CreateResourceAvailabilityException(
  resource_id,
  scope = all_locations,
  date/range,
  unavailable
)
```

while another is equivalent to:

```text
CreateResourceLocationAvailabilityException(
  assignment_id,
  date/range,
  unavailable
)
```

Final names depend on the minimal accepted implementation.

### 3.3 Concurrency/history

Resource-wide and assignment-scoped exceptions must participate in the same stale-option/revalidation contract. Existing Reservations/Claims keep their historical meaning; exception creation does not rewrite old commercial provenance.

### 3.4 Required tests

At minimum:

```text
assignment-specific closure does not affect another Location
Resource-wide closure suppresses all affected assignments
Resource-wide additional availability cannot bypass closed Location hours
concurrent broad + narrow exception writes produce deterministic effective state
booking after stale broad/narrow exception is rejected/recomputed correctly
```

---

## 4. Organization may be an independent physician/practice or a clinic

`Organization` is the tenant/security/administrative boundary. It must not be semantically equated with "clinic".

Both of these are valid tenant shapes:

```text
Organization: Dr. Juan Pérez / independent practice
  Location: private office
  Resource: Dr. Juan Pérez
  Offerings
```

and:

```text
Organization: Clínica Brugal
  Locations
  Resources: multiple physicians
  Offerings
```

F1 must not introduce constraints that assume every Organization contains multiple physicians or represents a facility company.

F2 discovery must treat both shapes as eligible participating Organizations when publication policy permits.

A physician may also appear as tenant-local Resources in multiple clinic Organizations and/or an independent-practice Organization, while hidden global/shared-capacity controls prevent double booking according to the already accepted cross-tenant design.

---

## 5. Organization-level public operational contact is separate from Location contact

The earlier F1 contract correctly introduced Location public operational contact endpoints, but a business may also have a central contact endpoint that is not owned by one branch.

Examples:

```text
central WhatsApp
central appointment phone
central email
```

F1 must support a minimal Organization-level public operational contact surface when required by `business.get_info`.

This does not imply CRM contact management.

### 5.1 Ownership/boundary

The implementation must not silently reuse Party/customer contact lifecycle merely because both contain phone/email-like values.

The accepted model may reuse a shared normalized ContactPoint value object/infrastructure, but ownership/publication semantics remain explicit:

```text
Organization public operational endpoint
Location public operational endpoint
PartyContactPoint identity
```

are different relationships/authorities.

### 5.2 Public query precedence

`business.get_info` may expose:

```text
Organization central public contact endpoints
Location-specific public contact endpoints
```

without implying that one automatically overrides the other. Consumers can choose the Location-specific endpoint when operating against a specific Location and use the central endpoint for business-level contact when appropriate.

---

## 6. F2 requires canonical cross-tenant service classification/mapping

Cross-tenant discovery cannot rely only on tenant-owned display strings.

Different tenants may name equivalent supply:

```text
Cardiología
Consulta cardiológica
Cardiólogo
Evaluación cardiovascular
```

F2 therefore has an explicit open design requirement:

> Provide a canonical classification/mapping mechanism sufficient for a platform query such as `cardiology` / `cardiólogo` to match compatible tenant-owned Offerings without requiring every tenant to use the same display label.

This mechanism must preserve:

```text
tenant-owned display names
versioned Offering identity
explicit publication control
no accidental semantic authority from fuzzy text alone
```

Possible solutions to evaluate in F2 include:

```text
platform service/category taxonomy + tenant mapping
stable capability/classification codes
curated mapping with controlled aliases
```

Do not choose the final model inside F1 without F2 security/search requirements.

This is an **open F2 design requirement**, not an F1 schema requirement.

---

## 7. F3 interruption/activity actions may be authorized to physician or staff

The roadmap already records emergency, medical-representative, break and administrative activities.

Clarification:

> Recording an operational interruption is not secretary-only.

A physician may record/start/end their own interruption when authorized, and authorized secretary/clinic staff may do so under clinic policy.

The eventual F3 command must record:

```text
actor Principal
recorded_by/provenance
Resource
Location/context
category
started_at/completed_at
```

and apply normal authorization rather than trusting UI role names.

---

## 8. Closed decisions vs intentionally open decisions

After this amendment, the following F1 semantics are closed:

```text
Location recurring hours need explicit Location-level exceptions
Resource-wide and Resource-at-Location exception intents are distinct
commercial Offering identity is not forced to equal future live workload classification
Organization is not synonymous with clinic
Organization-level and Location-level public operational contacts may both exist
```

The following remain deliberately open until their owning feature:

```text
exact persisted workload-classification entity/vocabulary -> F3
exact statistical estimator for workload/ETA -> F4
cross-tenant canonical service taxonomy persistence/model -> F2
exact discovery popularity formula -> F2/F4 data availability
exact ResourceActivity persistence model -> F3
```

Open does not mean forgotten. Each is a mandatory design question for the owning feature.

---

## 9. Implementation gate

Before the first F1 production migration is authored, the implementation inventory must prove how the current schema handles:

```text
Location hours
Location exceptions (currently absent or existing equivalent)
Resource schedule/exception scope
Resource-at-Location eligibility
Organization/Location public contacts
OfferingVersion duration/commercial terms
Reservation historical fields
```

The migration/schema design must explicitly satisfy sections 1–5 of this document.

Before F1 is declared merge-ready, the main `15-operational-profile-contextual-supply-contract.md` should be consolidated so these clarifications no longer depend on a separate amendment for everyday reading. Until that consolidation, this document is normative and takes precedence on the named points.