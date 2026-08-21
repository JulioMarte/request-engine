# Operational Profile & Contextual Supply — Implementation Handoff

Status: current execution handoff for `feature/operational-profile-contextual-supply`.

Checkpoint inspected through:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
```

Feature base / current `development` merge base:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

At this checkpoint the feature branch is ahead of `development` and behind by zero commits.

This document is an **implementation/status handoff**, not a new normative contract. It does not supersede the existing F1 precedence:

```text
docs/v3/16-operational-profile-contextual-supply-clarifications.md
  >
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Use this document to understand what has already been built, what has actually been proven, what remains incomplete, and the intended order for finishing the branch.

---

## 1. Original goal of this branch

F1 exists to make Request Engine authoritative for the structured operational facts required to answer and execute questions such as:

```text
Can I book cardiology tomorrow between 1 PM and 5 PM
at Clínica Brugal, with any eligible doctor, and what will it cost?
```

Without depending on Directus, RAG, Memory or manual orchestration for operational truth, RE must be able to determine:

```text
what Offering/OfferingVersion exists
where it can be delivered
which Resources are eligible at that Location
when the Location is operational
when each Resource works at that Location
which broad/narrow schedule exceptions apply
what fixed price and planned duration apply in the exact context
whether the concrete option is currently bookable
whether a previously discovered option became stale before commit
what commercial terms were historically committed after booking
```

The foundational design rule remains:

> Resource-at-Location configuration describes eligibility and operational context. `Resource` remains the capacity serialization root and `CapacityClaim` remains the authoritative capacity-consumption ledger.

F2+ concerns such as cross-tenant marketplace discovery, ranking, live workload, adaptive intake and operational copilot behavior remain outside this branch.

---

## 2. Phase status at this checkpoint

| Phase | Status | Current disposition |
| --- | --- | --- |
| A — documentation/architecture reconciliation | COMPLETE | F1 plan, roadmap, normative contract, clarification and ADR exist. |
| B — implementation inventory | COMPLETE | `17-operational-profile-contextual-supply-implementation-inventory.md` records old→new disposition. |
| C — relational schema | IMPLEMENTED; CURRENT CONSOLIDATED HEAD REQUIRES FRESH CI PROOF | F1 provisional revisions were consolidated into one unshipped Alembic `0002_f1_supply`. |
| D — domain/application model | SUBSTANTIALLY COMPLETE | Contextual supply domain values, contracts, commands, errors and option observations exist. |
| E — semantic configuration commands | SUBSTANTIALLY COMPLETE, WITH TWO SURFACE GAPS TO CLOSE/DECIDE | Organization operational profile, Location profile/hours/contacts, assignment/availability/exceptions and commercial terms are implemented. See §8. |
| F — deterministic query resolution | IMPLEMENTED | `business.get_info`, catalog contextual discovery and contextual/legacy slot resolution exist. |
| G — booking integration | IMPLEMENTED FOR DIRECT CONTEXTUAL BOOKING; LEGACY HOLD/RESCHEDULE ARE FAIL-CLOSED FOR CONTEXTUAL CHOICES | Contextual `find_slots`/`book`, stale revalidation, commercial commitment and assignment claim provenance exist. |
| H — adversarial proof | IN PROGRESS | Core shared-capacity, stale, provenance and config-vs-book races exist; remaining race matrix items are listed below. |

The branch must **not** be called merge-ready yet.

---

## 3. Relational schema now implemented

The implementation no longer uses a provisional `0002 → 0003 → 0004 → 0005` F1 development chain.

Because F1 has never been deployed with real customer data, those provisional revisions were mechanically consolidated into:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

The current migration contains the previously separated concerns in one intended launch revision:

```text
base operational/contextual schema
commercial source provenance
shared-capacity guard compatibility
runtime ACL/RLS hardening
```

The released V3 baseline remains untouched:

```text
migrations/versions/0001_initial.py
migrations/sql/v3_candidate/*
migrations/sql/v3_initial/*
migrations/sql/design_chain/*
```

### 3.1 Existing relations extended

F1 extends at least:

```text
organizations
  legal_name
  default_timezone
  default_locale
  default_currency
  operational_status

locations
  structured address fields
  country_code
  latitude / longitude
  geocoding provenance
  operational_revision

capacity_claims
  resource_location_assignment_id nullable provenance
```

Legacy rows remain valid. Legacy claims do not invent historical assignment provenance.

### 3.2 New operational relations

The consolidated schema includes the F1 operational relations described by the accepted Phase C design, including:

```text
organization_public_contact_endpoints
location_public_contact_endpoints
location_operational_hours
location_hours_exceptions
resource_location_assignments
resource_location_availability
resource_location_schedule_exceptions
offering_version_booking_terms
booking_context_terms
reservation_commercial_commitments
reservation_commercial_commitment_context_terms
```

The exact migration is authoritative over the earlier pre-authoring wording in `18-operational-profile-contextual-supply-relational-schema.md`.

One documentation mismatch still needs cleanup before merge: the schema design document says `public boolean` for contact rows, while the executable schema uses `is_public boolean`.

### 3.3 Material observation/revision model

Current implementation uses material observation tokens rather than pretending every aggregate has a single universal revision:

```text
Location operational_revision
Resource availability_revision
ResourceLocationAssignment revision
BookingContextTerms revision
configuration fingerprint on contextual AppointmentOption
```

These are used to detect stale configuration at authoritative booking time.

---

## 4. Contextual schedule model implemented

The contextual path implements the intended composition boundary:

```text
Location recurring operational hours
APPLY Location closures/additional-hours exceptions
=
effective Location availability

INTERSECT Resource-at-Location recurring availability
APPLY Resource-wide + assignment-specific exceptions
THEN revalidate capacity
```

Important preserved rules:

```text
Resource additional availability cannot open a closed Location by itself.
A narrow assignment-specific exception does not silently become Resource-wide.
A Resource-wide exception remains broad across applicable assignments.
Recurring local time uses the Location IANA timezone.
Concrete intervals are timezone-aware half-open [start,end).
```

The legacy V3 Resource schedule path remains available only for Resources that have not entered contextual assignment semantics.

Once a Resource has contextual assignment history, the resolver does not silently fall back to V3 wildcard Location behavior after an assignment retires.

---

## 5. Contextual pricing and commercial provenance implemented

The deterministic F1 commercial rule is implemented as:

```text
exact effective ResourceLocationAssignment + OfferingVersion contextual terms
>
OfferingVersion immutable/base terms
>
missing required terms => not quoteable/bookable
```

Supported contextual values remain intentionally narrow:

```text
fixed amount
currency
planned duration
bookable state
effective dating
```

No formula engine, surge pricing, coupons or arbitrary inheritance graph was introduced.

A successful contextual Reservation persists immutable commercial commitment information, including the resolved amount/currency/duration and the source contextual term rows required to explain why those terms applied.

The current temporal-provenance suite also covers:

```text
future contextual terms activating at the effective boundary
future booking committing the exact future source row
existing CapacityClaim preventing assignment-history rewrite
```

---

## 6. AppointmentOption and `find_slots` implementation

Released V3 `aptopt_v1` remains semantically intact for the legacy path.

F1 adds a versioned contextual token:

```text
aptopt_v2
```

The contextual option binds material observations including:

```text
Organization / OfferingVersion
start/end
Location
selected Resources
ResourceLocationAssignment id/revision when contextual
Resource availability revision
planned duration
amount/currency
Location operational revision
configuration fingerprint
issued/expires timestamps
```

Mixed contextual + legacy Resource selection is represented explicitly rather than serializing missing assignment ids as strings.

`PostgresAppointmentAvailabilityReader` now provides two deliberate paths:

```text
legacy V3 path
  preserve released behavior

contextual/mixed F1 path
  resolve assignment eligibility
  resolve Location + Resource schedules/exceptions
  resolve exact/base commercial terms
  respect advisory capacity
  emit material configuration observation
```

Catalog contextual discovery also verifies that a requested active Location has sufficient effective Resource assignment/capability supply rather than advertising a service solely because an Offering exists.

---

## 7. Authoritative contextual `book` implementation

Direct contextual booking is implemented through `PostgresContextualReservationCommands`.

Inside the authoritative transaction it performs/reuses the expected protocol:

```text
idempotency
Offering lock/current bookable state
subject/location/origin validation
subject authority
Location lock + expected operational revision
requirement cardinality
Resource locks
capability validation
selected assignment locks/current assignment state
Resource availability revision validation
contextualization resolution
Location + Resource schedule composition
live capacity revalidation
commercial terms re-resolution
configuration fingerprint comparison
shared-capacity serialization when applicable
Reservation insert
CapacityClaim insert with assignment provenance
immutable commercial commitment + source provenance
audit/outbox/idempotency completion
```

A materially changed price/context is rejected as stale. The booking path never silently substitutes a different price from the option the caller accepted.

### 7.1 Shared-capacity compatibility

The contextual path continues to serialize capacity at the underlying Resource and preserves the existing shared-capacity mutex/binding behavior.

There is an explicit F1 integration test for contextual shared-capacity contention.

### 7.2 Hold/reschedule boundary

Contextual CapacityHold and contextual reschedule are **not** implemented as full F1 contextual flows in this branch yet.

The safe current behavior is fail-closed:

```text
contextual ResourceChoice -> legacy CapacityHold path => rejected
contextual ResourceChoice -> legacy reschedule path => rejected
```

The guard exists in the commitment boundary, not only in the HTTP router, so internal callers cannot bypass it accidentally.

This is intentional safety, not feature completeness for contextual hold/reschedule.

---

## 8. Semantic configuration command status

### Implemented

#### Tenancy

```text
UpdateOrganizationOperationalProfile
```

Current typed fields:

```text
legal_name
default_timezone
default_locale
default_currency
operational_status
```

#### Catalog / Location

```text
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
```

These use semantic authority/idempotency/audit patterns and material revision behavior where booking state is affected.

#### Booking contextual supply

```text
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

Future terms do not require a separate storage model: `ConfigureBookingContextTerms` supports effective dating and the temporal suite proves future activation.

### Remaining semantic-surface decisions/gaps

Two F1 plan surfaces are not represented by an obvious dedicated command today:

1. **CreateLocation** — there is no F1-specific semantic `CreateLocation` command in the current Catalog command package. Before merge, either implement it or explicitly document which existing provisioning path owns initial Location creation and why that satisfies the F1 contract.
2. **Organization public operational contact mutation** — schema and `business.get_info` read support exist for Organization public contacts, but there is no corresponding dedicated semantic mutation command visible alongside `UpdateOrganizationOperationalProfile`. Either add it or explicitly narrow/reconcile the contract.

Do not solve either gap with generic CRUD or direct SQL as the public configuration path.

---

## 9. Public operational query status

`business.get_info` now has typed F1 additions while retaining released compatibility fields.

It can represent:

```text
Organization display identity
legal/default operational profile
Organization public contact endpoints
Locations
structured Location address
Location public contacts
Location timezone
recurring operational hours
Location hours exceptions
```

`catalog.search_offerings` / version-aware offering data now include applicable base commercial terms and contextual Location/effective-supply filtering where requested.

The current implementation keeps presentation-oriented legacy JSON fields for compatibility but does not use them as F1 operational authority.

---

## 10. Proof already added to the repository

The F1 PostgreSQL runner currently includes:

```text
test_schema.py
test_runtime_privileges.py

test_business_info.py
test_catalog_contextual_discovery.py

test_operational_commands.py
test_operational_profile_commands.py
test_contextual_config_commands.py
test_contextual_supply_lifecycle_commands.py

test_contextual_booking.py
test_contextual_booking_races.py
test_contextual_temporal_provenance.py
test_contextual_shared_capacity.py

released V3 booking core regression
released V3 booking commitments regression
```

Unit/module proof also exists for contextual resolution, `aptopt_v1` compatibility, `aptopt_v2`, mixed Resource observations and fail-closed contextual commitment boundaries.

### 10.1 Config-vs-book concurrency tests now present

The branch contains real PostgreSQL lock/race tests for:

```text
context price mutation concurrent with book
Location closure concurrent with book
ResourceLocationAssignment retirement concurrent with book
```

The tests deliberately acquire the same serialization roots used by production, start booking concurrently, prove the booking cannot pass the lock out of order, commit the configuration mutation, and require the booking to resume as `AppointmentOptionStale` with no partial Reservation.

### 10.2 Historical/temporal provenance tests now present

The branch also contains explicit proof that:

```text
a committed contextual CapacityClaim prevents rewriting assignment history so the claim falls outside the assignment range;
future contextual terms activate at their effective boundary;
a future Reservation persists the exact future commercial source row.
```

---

## 11. CI evidence: proven vs not yet proven

This distinction is important.

### Last fully green checkpoint observed during implementation

```text
commit: 57fc5d7bb8adbf8f0a9df50fa9644f38f594fa0d
workflow run: 32484833747
```

That run was fully green across:

```text
Python quality and architecture
PostgreSQL 18 V2 design history
PostgreSQL 18 V3 repeated bootstrap proof
Observability runtime contract
PostgreSQL 18 F1 operational profile and contextual supply
PostgreSQL 18 frozen V3 compatibility
PostgreSQL 18 V3 candidate and verticals aggregate
```

However, important hardening was added **after** that checkpoint, including the explicit booking races, temporal provenance proof and consolidated single F1 migration. Therefore the old green run is evidence for the earlier implementation state, not proof of the current tree.

### Later red checkpoint that exposed only formatting

At `bd25f8c364bdc30b48cd57cd24beb7a5587f2193`, run `32485522827` stopped in Python quality because `test_contextual_booking_races.py` needed Ruff formatting. PostgreSQL jobs were skipped.

That test is now formatted in the current tree.

### Current checkpoint immediately before this handoff

After migration consolidation, the temporary consolidator workflow was removed and the one-shot consolidation helper was also removed because it had become the only Ruff blocker.

The implementation checkpoint is:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
```

The immediately preceding run at `1788d41be0f7217f72477c40cb94ccd5c34f7887` (`32498462010`) failed only in Ruff E501 on the now-deleted one-shot consolidation helper. PostgreSQL did not run on that SHA.

Therefore the consolidated `0002_f1_supply` plus the newest race/provenance tests still require one **fresh full green CI run** before any merge-readiness claim.

---

## 12. Remaining race/adversarial matrix

The plan in `13-operational-profile-contextual-supply-plan.md` requires falsification attempts beyond happy-path tests.

Current disposition:

| Required scenario | Status at checkpoint | Next action |
| --- | --- | --- |
| Price changes after discovery before book | IMPLEMENTED | Keep deterministic race green. |
| Assignment retires after discovery before book | IMPLEMENTED | Keep deterministic race green. |
| Schedule exception added after discovery before book | PARTIAL | Add explicit Resource-wide and/or assignment-specific schedule-exception race; current Location-closure race is not the same scope. |
| Location hours change after discovery | PARTIAL | Location-hours exception closure race exists; add/confirm recurring-hours mutation stale proof if contract requires both mutation forms. |
| Offering becomes non-bookable/inactive after discovery | NOT EXPLICITLY PROVEN | Add stale-option integration test under authoritative Offering lock/current-state revalidation. |
| Concurrent overlapping effective contextual-term writes | STRUCTURALLY GUARDED; CONCURRENT PROOF INCOMPLETE | Add two-transaction concurrency test against exclusion/serialization behavior. |
| Concurrent overlapping assignment/schedule writes | STRUCTURALLY GUARDED; CONCURRENT PROOF INCOMPLETE | Add two-transaction race tests, not only sequential conflict tests. |
| Configuration mutation concurrent with Booking | IMPLEMENTED CORE SET | Price, Location closure and assignment retirement races exist. |
| Existing Reservation remains explainable after config changes | SUBSTANTIALLY IMPLEMENTED | Commercial commitment/source and temporal provenance exist; add any missing schedule-history explanation assertion only if needed. |
| Existing CapacityClaim provenance cannot be invalidated | IMPLEMENTED | Temporal provenance test expects SQLSTATE `55000`. |
| Duplicate display names cannot create authority confusion | NOT EXPLICITLY PROVEN | Add authority test using duplicate human-readable names and distinct IDs. |
| Timezone/DST boundary | BASE DOMAIN LOGIC EXISTS; F1-SPECIFIC PROOF SHOULD BE CONFIRMED | Add contextual Location/assignment DST gap/fold test or explicitly cite existing reusable proof if equivalent. |
| Cross-tenant guessed IDs remain opaque | PARTIAL/COMMAND TESTED | Audit all new public mutation/query surfaces and add API-level opacity proof where missing. |
| Contextual booking cannot bypass shared capacity | IMPLEMENTED | Existing contextual shared-capacity integration test. |
| Public contact mutation cannot cross tenant | LOCATION PATH TESTED; ORGANIZATION WRITE SURFACE MISSING | Complete Organization contact command and tenant proof if retained in F1. |

Do not mark Phase H complete until this table is either green or a named row is explicitly removed from the normative contract with rationale.

---

## 13. Additional cleanup before merge

### 13.1 Documentation reconciliation

Before merge:

1. Fold closed clarifications from `16-operational-profile-contextual-supply-clarifications.md` into the owning sections of `15` / `13` so readers do not need a permanent amendment chain.
2. Reconcile `18-operational-profile-contextual-supply-relational-schema.md` with the as-built migration, including `is_public` naming and consolidated `0002_f1_supply` status.
3. Update Phase status in the main plan once proof is complete.
4. Keep ADR 0012 `Proposed` until implementation/evidence satisfies its proof conditions; only then consider `Accepted`.
5. Ensure this handoff is either converted into final implementation evidence or clearly retained as a historical checkpoint after merge.

### 13.2 CI/repository cleanup

Before merge:

```text
remove branch-only push trigger for feature/operational-profile-contextual-supply from ci.yml;
remove any leftover one-shot/temporary development tooling;
verify no temporary workflow remains;
verify pyproject/Ruff exceptions are still justified and narrow;
check whether both tests/modules/booking/test_contextual_commitment_boundary.py and tests/unit/test_contextual_commitment_boundary.py add distinct value or should be consolidated;
run final exact-head canonical CI after cleanup.
```

### 13.3 Error contract refinement

The fail-closed contextual hold/reschedule boundary currently reuses `InvalidResourceSelection`.

Safety is correct, but before merge decide whether the public/API contract benefits from a dedicated machine-readable error such as a contextual-operation-not-supported/stale contract rather than overloading generic resource selection failure.

Do not weaken the fail-closed behavior while refining error taxonomy.

---

## 14. Exact continuation plan

The intended continuation order is:

### Step 1 — get the current consolidated tree green

Run the canonical branch CI on the current head after removal of the one-shot consolidation helper.

Require green for:

```text
Python quality + Ruff + Pyright + architecture + unit/module tests
F1 Alembic clean bootstrap to 0002_f1_supply
F1 schema/RLS/runtime privilege proof
F1 semantic commands
F1 business/catalog queries
F1 contextual booking/races/provenance/shared-capacity
released V3 booking regression
frozen V3 compatibility
V2 design history
repeated V3 bootstrap
observability
aggregate required status
```

If the current F1 PostgreSQL suite reveals a lock-order, trigger, revision, migration or semantic failure, fix the implementation. Do not weaken/remove the failing adversarial test merely to obtain green CI.

### Step 2 — finish the remaining Phase H race matrix

Prioritize:

```text
Resource-wide/assignment-specific schedule-exception vs book
Offering current-state mutation vs book
concurrent overlapping contextual-term writes
concurrent assignment/schedule writes
duplicate-name authority proof
contextual DST gap/fold proof
```

Run the F1 job after each logically grouped hardening change rather than creating unnecessary CI spam.

### Step 3 — close semantic configuration surface gaps

Decide and implement/document:

```text
CreateLocation ownership/path
Organization public operational contact mutation
```

Any added write must use the established authority + idempotency + audit + tenant/RLS contract.

### Step 4 — complete API/capability proof

Add/confirm end-to-end capability/API proof for:

```text
business.get_info typed safe public operational fields
catalog contextual Location/effective filtering
find_slots 13:00–17:00 resource=any behavior
aptopt_v2 -> contextual book
machine-readable stale response
aptopt_v2 contextual reschedule rejection while legacy aptopt_v1 reschedule remains valid
foreign-tenant opacity on new surfaces
```

### Step 5 — reconcile docs with the as-built implementation

Consolidate clarification `16`, update relational schema `18`, update plan status and ADR state only when justified by proof.

### Step 6 — final repository cleanup

Remove feature-only CI trigger and any remaining one-shot scaffolding, resolve duplicate tests if appropriate, and confirm no frozen V3 files were modified.

### Step 7 — exact-head merge-readiness proof

On the final cleaned head:

```text
compare against current development
require behind_by = 0 or reconcile any new development changes
run full canonical CI
inspect every required check
verify migration head = 0002_f1_supply
verify 0001/frozen V3 provenance unchanged
verify F1 and released-V3 regressions green
verify no temporary workflow/tooling remains
```

Only after this exact-head proof should the branch be called ready for PR/merge.

---

## 15. What must not change while finishing

Do not solve remaining failures by violating the closed F1 decisions:

```text
Do not modify 0001_initial.
Do not mutate frozen V3 candidate/design history.
Do not make ResourceLocationAssignment a second capacity ledger.
Do not allow Resource additional availability to bypass a closed Location.
Do not collapse Resource-wide and assignment-specific exceptions.
Do not silently fall back a contextualized Resource to legacy wildcard Location semantics.
Do not silently change price during book.
Do not reconstruct historical committed price solely from mutable current configuration.
Do not remove assignment provenance from contextual CapacityClaim.
Do not weaken shared-capacity serialization.
Do not allow contextual hold/reschedule through V3 just because the contextual version is not implemented yet.
Do not replace semantic commands with generic CRUD/admin SQL.
Do not expand F1 into F2/F3/F4/F5/F6 scope.
```

---

## 16. Definition of the next meaningful milestone

The next milestone is **not** “more code exists.”

The next meaningful milestone is:

> the consolidated `0002_f1_supply` current tree, including race/provenance hardening, passes full branch CI; then the remaining explicit Phase H gaps are closed without weakening the normative F1 invariants.

After that, the branch can move from implementation/hardening into documentation consolidation and exact-head merge-readiness review.
