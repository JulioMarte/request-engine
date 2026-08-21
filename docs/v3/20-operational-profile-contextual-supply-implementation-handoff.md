# Operational Profile & Contextual Supply — Implementation Handoff

Status: current execution handoff for `feature/operational-profile-contextual-supply`.

Implementation checkpoint audited:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
```

Feature base / merge base with `development`:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

At the documentation audit immediately following that implementation checkpoint, the branch was:

```text
ahead of development: 206 commits
behind development: 0 commits
```

The commits after `9d070685...` and before this documentation refresh were documentation-only, so this handoff describes the same implementation tree.

This document is an **informative implementation/status handoff**, not a new normative contract.

Normative F1 precedence remains:

```text
docs/v3/16-operational-profile-contextual-supply-clarifications.md
  >
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Detailed cross-document audit and mismatch registry:

```text
docs/v3/21-operational-profile-contextual-supply-documentation-audit.md
```

Use this handoff to resume implementation without reconstructing prior decisions from chat/history.

---

## 1. Feature objective

F1 exists to make Request Engine authoritative for the structured operational facts required to answer and execute questions such as:

```text
Can I book cardiology tomorrow between 1 PM and 5 PM
at Clínica Brugal, with any eligible doctor, and what will it cost?
```

RE must determine from its own operational truth:

```text
Offering/OfferingVersion
Location
Resource eligibility at that Location
Location operational schedule
Resource-at-Location schedule
broad/narrow exceptions
planned duration
fixed applicable amount/currency
current capacity
stale configuration between discovery and commit
historical commercial commitment after booking
```

The foundational design rule remains:

> Resource-at-Location configuration describes eligibility and operational context. `Resource` remains the capacity serialization root and `CapacityClaim` remains the authoritative capacity-consumption ledger.

F2+ marketplace/discovery, live workload, adaptive intake, service telemetry and natural-language operational-copilot concerns remain outside this branch.

---

## 2. Phase status

| Phase | Status | Current disposition |
| --- | --- | --- |
| A — documentation/architecture reconciliation | COMPLETE at design foundation; FINAL CONSOLIDATION PENDING | Plan, roadmap, contract, clarification, ADR and branch index exist. `16` still needs folding into `15/13` before merge readiness. |
| B — implementation inventory | COMPLETE | `17` records the old->new disposition used before SQL authoring. |
| C — relational schema | IMPLEMENTED AND CONSOLIDATED; ONE P0 COMMERCIAL-SOURCE DEFECT FOUND BY AUDIT | One unshipped `0002_f1_supply`; schema/RLS/ACL/shared-capacity compatibility exist. See §11. |
| D — domain/application model | SUBSTANTIALLY COMPLETE | Contextual terms, schedules, option observations, commands/errors and booking contracts exist. |
| E — semantic configuration commands | SUBSTANTIALLY COMPLETE; TWO SURFACE GAPS | `CreateLocation` ownership/path and Organization central public-contact mutation remain unresolved. |
| F — deterministic query resolution | IMPLEMENTED | `business.get_info`, catalog contextual filtering and contextual/mixed slot resolution exist. |
| G — direct contextual booking | IMPLEMENTED | `aptopt_v2 -> book`, authoritative revalidation, assignment claim provenance and immutable commercial commitment exist. |
| G — contextual hold/reschedule | SAFE FAIL-CLOSED, NOT FULLY CONTEXTUAL | Contextual choices cannot silently use released V3 hold/reschedule semantics. Final F1 scope disposition still needs explicit closure. |
| H — adversarial proof | IN PROGRESS | Core races/provenance/shared-capacity are present; explicit remaining matrix is in §13. |

The branch is **not merge-ready** yet.

---

## 3. Current production migration shape

The provisional F1 development revisions were consolidated because F1 has never been deployed with customer-owned data.

Current production-history delta:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

The one migration contains:

```text
operational/contextual schema
commercial source provenance
shared-capacity guard compatibility
runtime ACL/RLS hardening
```

The released V3 baseline remains immutable:

```text
migrations/versions/0001_initial.py
migrations/sql/v3_candidate/*
migrations/sql/v3_initial/*
migrations/sql/design_chain/*
```

No migration-time invention of historical contextual assignments or historical commercial commitments is performed for legacy V3 rows.

---

## 4. As-built schema summary

### Existing relations extended

```text
organizations
  legal_name
  default_timezone
  default_locale
  default_currency
  operational_status

locations
  structured address
  country_code
  latitude/longitude
  geocoding provenance
  operational_revision

capacity_claims
  nullable resource_location_assignment_id provenance
```

### New F1 relations

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

Contact rows use:

```text
is_public boolean
```

not the earlier design-document spelling `public boolean`.

The final runtime ACL intentionally gives **no direct authoritative F1 relation privileges to `request_engine_worker`**. Tenant-domain handlers use the `request_engine_app` side of Production Worker Assembly. This is part of the final migration state, even though the base SQL block briefly grants roles before the later hardening block revokes worker access.

---

## 5. Schedule semantics implemented

Contextual scheduling resolves:

```text
Location recurring operational hours
APPLY Location-level available/unavailable exceptions
=
effective Location operational availability

INTERSECT
Resource-at-Location recurrence
APPLY Resource-wide + assignment-specific Resource exceptions
INTERSECT explicit contextual temporal restrictions where configured
THEN capacity revalidation
```

Preserved rules:

```text
Resource additional availability cannot open a closed Location.
Assignment-specific exceptions never silently become Resource-wide.
Resource-wide exceptions remain broad.
Recurring wall-clock rules use the Location IANA timezone.
Concrete intervals are timezone-aware half-open [start,end).
```

Legacy Resource recurrence remains only for Resources that have never entered contextual assignment semantics.

Once a Resource has contextual assignment history, it does not silently regain legacy wildcard Location eligibility after an assignment retires.

---

## 6. Commercial resolution implemented

F1 deterministic resolution remains:

```text
exact effective ResourceLocationAssignment + OfferingVersion contextual terms
>
OfferingVersion base/default terms
>
missing required amount/currency/duration => not quoteable/bookable
```

Supported values are intentionally narrow:

```text
fixed amount
currency
planned duration
bookable state
effective dating
```

No pricing DSL, surge pricing, coupon engine, insurance adjudication or arbitrary inheritance graph exists.

Future effective contextual terms are implemented through the same `ConfigureBookingContextTerms` lifecycle rather than a separate future-pricing aggregate.

The temporal-provenance suite proves:

```text
future contextual term activation at the effective boundary
future booking preserving the exact contextual source row
existing CapacityClaim preventing assignment-history rewrite
```

---

## 7. `AppointmentOption` and slot discovery

Released V3 token:

```text
aptopt_v1
```

remains the legacy path.

F1 contextual token:

```text
aptopt_v2
```

binds material observations including:

```text
Organization/OfferingVersion
start/end
Location
selected Resource IDs
assignment ID/revision where contextual
Resource availability revisions
planned duration
amount/currency
Location operational revision
configuration fingerprint
issued/expires timestamps
```

Mixed contextual + legacy Resources are represented explicitly. A legacy member of a mixed contextual option has no fabricated assignment ID.

`PostgresAppointmentAvailabilityReader` deliberately has:

```text
legacy V3 resolution
contextual/mixed F1 resolution
```

The F1 path resolves assignment eligibility, Location/Resource schedules, broad/narrow exceptions, commercial terms, advisory capacity and material configuration observations.

Catalog contextual discovery also verifies effective Resource assignment/capability supply at the requested active Location instead of advertising an Offering solely because it exists.

---

## 8. Authoritative contextual `book`

Direct contextual booking is implemented by `PostgresContextualReservationCommands`.

The authoritative transaction performs/reuses:

```text
idempotency
OfferingVersion lock/current state
subject/Location/origin validation
subject authority
Location lock + operational revision
requirement cardinality
Resource locks in canonical order
capability validation
selected assignment locks/current state
Resource availability revision checks
contextualization resolution
Location/Resource schedule composition
live capacity revalidation
commercial re-resolution
configuration fingerprint comparison
shared-capacity serialization where bound
Reservation insert
CapacityClaim insert with assignment provenance
immutable commercial commitment
0..N contextual commercial source links
audit/outbox/idempotency completion
```

A material mismatch is stale. Booking never silently changes price.

A successful contextual claim records the exact `resource_location_assignment_id` when one applied.

---

## 9. Shared-capacity compatibility

The F1 contextual flow keeps `Resource` as the tenant-local capacity root and preserves released cross-tenant shared-capacity serialization.

The consolidated migration retains the narrow privileged shared-capacity guard responsibility while moving contextual assignment validation into a tenant-local invoker trigger so FORCE RLS remains meaningful.

There is an explicit integration test proving contextual booking cannot bypass shared-capacity contention.

---

## 10. Contextual hold/reschedule boundary

Full contextual CapacityHold/reschedule flows are not implemented.

The safe current behavior is:

```text
contextual ResourceChoice -> released V3 CapacityHold path => rejected
contextual ResourceChoice -> released V3 reschedule path => rejected
legacy V3 hold/reschedule => unchanged
```

The guard exists at the commitment boundary, not only at HTTP routing, so internal callers cannot bypass it accidentally.

Before merge, explicitly decide whether this fail-closed behavior satisfies F1 scope or whether full contextual hold/reschedule is required. Do not allow an accidental pass-through to V3 semantics.

The current unsupported-path error reuses `InvalidResourceSelection`; a dedicated machine-readable error may be clearer if fail-closed is retained as the final F1 contract.

---

## 11. P0 blocker discovered during documentation audit

This is the most important new finding from the documentation/code reconciliation.

### Current schema

`reservation_commercial_commitments` still contains:

```text
offering_version_booking_terms_id uuid NULL
booking_context_terms_id uuid NULL
```

and a CHECK requiring:

```text
offering_version_booking_terms_id IS NOT NULL
OR booking_context_terms_id IS NOT NULL
```

Later F1 hardening added the correct multi-source relation:

```text
reservation_commercial_commitment_context_terms
```

### Current writer

The contextual booking writer now:

```text
inserts offering_version_booking_terms_id = base_terms.source_id
DOES NOT populate reservation_commercial_commitments.booking_context_terms_id
inserts every effective contextual source into reservation_commercial_commitment_context_terms
```

This correctly avoids inventing one arbitrary "primary" contextual source for a multi-resource Offering.

### Failure case

F1 explicitly allows:

```text
no OfferingVersion base-price row
+
exact contextual term supplies amount/currency
+
OfferingVersion supplies planned duration
```

`BaseBookingTerms.source_id` is therefore legitimately `NULL` in a context-only pricing scenario.

The resolver can produce complete valid terms, but the commitment insert can then have:

```text
offering_version_booking_terms_id = NULL
booking_context_terms_id = NULL
```

before the bridge rows are inserted. The row CHECK can reject an otherwise valid contextual booking.

### Required correction

Before merge:

1. remove the obsolete single-source `booking_context_terms_id` from the still-unshipped F1 migration unless a concrete use remains;
2. remove/rework the row CHECK so context-only terms can commit;
3. retain optional base-source provenance;
4. retain the bridge as canonical 0..N contextual-source provenance;
5. add a context-only price integration test;
6. add/keep multi-resource provenance proof that every contributing contextual source is preserved.

Do not paper over this by forcing every OfferingVersion to have base price; that would contradict the accepted exact-context fallback contract.

---

## 12. Semantic configuration commands

### Implemented

Tenancy:

```text
UpdateOrganizationOperationalProfile
```

Catalog:

```text
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
```

Booking:

```text
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

These use the established authority/idempotency/audit/revision patterns where applicable.

### Remaining surface gaps

#### `CreateLocation`

There is no dedicated F1 semantic `CreateLocation` command visible in the current Catalog command surface.

Before merge either:

```text
implement the semantic creation path
```

or:

```text
identify/document the existing provisioning capability that owns initial Location creation
and prove it satisfies F1 authority/idempotency/audit/tenant requirements
```

Do not substitute generic CRUD/direct SQL as the public business path.

#### Organization public operational contacts

Schema and `business.get_info` read support exist for central Organization contacts, but no dedicated semantic mutation command exists.

Because clarification `16` explicitly requires Organization-level public operational contacts as distinct from Location contacts, this remains an F1 gap unless the normative contract is deliberately narrowed.

---

## 13. Adversarial proof disposition

### Already present

```text
price mutation concurrent with book
Location closure concurrent with book
assignment retirement concurrent with book
contextual shared-capacity contention
future contextual term activation
future booking source provenance
CapacityClaim assignment-history protection
schema/RLS/runtime privilege tests
cross-tenant structural tests
aptopt_v1 compatibility
aptopt_v2 round-trip/material observation
mixed contextual/legacy option representation
contextual hold/reschedule boundary fail-closed
```

### Remaining explicit proof

```text
context-only commercial booking with no base terms
assignment-specific schedule exception vs book race
Resource-wide exception vs book race
recurring Location-hours mutation vs book
OfferingVersion current-state mutation vs book
concurrent overlapping BookingContextTerms writes
concurrent overlapping assignment/schedule writes
duplicate display-name authority ambiguity proof
contextual DST gap/fold integration proof
foreign-tenant opacity across every new public API/capability
Organization contact mutation tenant proof after command exists
```

Do not mark Phase H complete by deleting or weakening tests. A required row can leave F1 only by an explicit normative scope decision.

---

## 14. Current CI evidence

### Older full green checkpoint

```text
commit: 57fc5d7bb8adbf8f0a9df50fa9644f38f594fa0d
run: 32484833747
```

That run was fully green, but it predates later race/provenance hardening and the final consolidated migration.

### Current implementation checkpoint evidence

```text
commit: 9d07068520da48950189ff78b70e80fb1bc1786d
run: 32498624044
```

Results on that implementation tree:

```text
PASS  Python quality and architecture
PASS  PostgreSQL 18 F1 operational profile and contextual supply
PASS  PostgreSQL 18 V2 design history
PASS  PostgreSQL 18 V3 repeated bootstrap proof
PASS  Observability runtime contract
CANCELLED PostgreSQL 18 frozen V3 compatibility
FAIL aggregate only because the prerequisite above was cancelled
```

The frozen-V3 job was cancelled by a later branch push while it was running; it was not a demonstrated product failure.

Therefore the consolidated migration + current F1 suite have real positive evidence, but there is still no fresh **exact-head all-required-jobs green** run after final documentation/cleanup.

Do not claim merge readiness until that run exists.

---

## 15. API/capability proof still required

Before merge readiness, explicitly prove the public/application surface rather than relying only on adapter tests:

```text
business.get_info exposes typed safe operational fields
Organization and Location public contacts remain tenant-safe
catalog Location/effective-supply filtering
find_slots within normalized 13:00-17:00 window
find_slots with any eligible Resource/provider
aptopt_v2 -> contextual book
stale option becomes machine-readable conflict without partial state
contextual aptopt_v2 reschedule is fail-closed if retained as contract
legacy aptopt_v1 reschedule remains valid
foreign-tenant guessed IDs remain opaque
```

---

## 16. Documentation work still required

`16-operational-profile-contextual-supply-clarifications.md` still has higher precedence on its named points.

Before merge readiness:

1. fold its closed F1 decisions into the owning sections of `15` and `13`;
2. keep genuinely future F2/F3 questions in the roadmap/owning future feature docs;
3. keep `17` as historical Phase B inventory;
4. keep `18` reconciled with the executable as-built schema;
5. keep this handoff current until final exact-head evidence exists;
6. keep ADR 0012 `Proposed` until the implementation/proof conditions are actually complete.

---

## 17. Repository cleanup before final proof

Before the final merge-readiness run:

```text
remove feature-only push trigger from .github/workflows/ci.yml
verify no temporary/one-shot workflow/tool remains
review F1-specific Ruff exceptions and keep only justified narrow entries
check whether tests/modules/booking/test_contextual_commitment_boundary.py
  and tests/unit/test_contextual_commitment_boundary.py are redundant
verify no frozen V3 source/provenance file was modified
```

Do cleanup only after the high-value implementation/proof work is complete so the final CI run corresponds to the actual merge candidate.

---

## 18. Exact continuation plan

### Step 1 — fix the P0 commercial-source defect

Correct the commitment schema/writer contract for context-only pricing and add direct regression proof.

### Step 2 — run focused quality + F1 PostgreSQL proof

Require:

```text
Ruff/Pyright/architecture/unit green
Alembic head exactly 0002_f1_supply
schema/RLS/runtime privilege green
semantic commands green
business/catalog green
contextual booking/races/provenance/shared-capacity green
released V3 booking regressions inside F1 runner green
```

### Step 3 — close semantic-surface decisions

Resolve:

```text
CreateLocation
Organization public operational contact mutation
contextual hold/reschedule final F1 scope
error taxonomy for unsupported contextual commitment flows
```

### Step 4 — finish remaining Phase H races

Highest-value order:

```text
Resource-wide + assignment-specific exception vs book
Offering current-state vs book
concurrent contextual-term writes
concurrent assignment/schedule writes
Location recurrence vs book
duplicate-name authority
DST gap/fold
foreign-tenant public-surface opacity
```

### Step 5 — complete API/capability tests

Cover §15 end-to-end.

### Step 6 — consolidate normative docs

Fold closed `16` F1 clarifications into `15/13`, update phase status and leave future scope in the roadmap.

### Step 7 — cleanup branch-only scaffolding

Remove feature push CI trigger/temporary leftovers and resolve redundant tests.

### Step 8 — exact-head merge-readiness proof

On the cleaned final head:

```text
compare against current development
require behind_by = 0 or reconcile new development work
run full canonical CI
inspect every required job
verify migration head = 0002_f1_supply
verify 0001/frozen V3 provenance unchanged
verify F1 + released-V3 regressions green
verify no temporary workflow/tooling remains
```

Only then consider ADR 0012 `Accepted` and call this branch ready for PR/merge.

---

## 19. Non-negotiable decisions while finishing

Do not solve remaining work by violating these closed decisions:

```text
Do not modify 0001_initial.
Do not mutate frozen V3 candidate/design history.
Do not make ResourceLocationAssignment a second capacity ledger.
Do not let Resource additional availability bypass a closed Location.
Do not collapse Resource-wide and assignment-specific exceptions.
Do not silently fall back contextualized Resources to legacy wildcard Location semantics.
Do not silently substitute a new price during book.
Do not reconstruct committed historical price solely from mutable current configuration.
Do not remove assignment provenance from contextual CapacityClaims.
Do not weaken shared-capacity serialization.
Do not send contextual hold/reschedule through V3 semantics by convenience.
Do not replace semantic commands with generic CRUD/admin SQL.
Do not expand F1 into F2/F3/F4/F5/F6 scope.
```

---

## 20. Next meaningful milestone

The next milestone is not merely another green unit suite.

It is:

> fix the context-only commercial commitment blocker, keep the consolidated `0002_f1_supply` and current adversarial suite green, close the remaining explicit semantic/proof gaps, then produce one cleaned exact-head canonical CI run with every required job green.

That is the point at which a merge-readiness review becomes meaningful.