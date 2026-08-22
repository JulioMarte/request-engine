# Operational Profile & Contextual Supply — Implementation Handoff

Status: current execution handoff for `feature/operational-profile-contextual-supply`.

This document is informative status/evidence guidance. Product semantics remain owned by:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Testing/evidence semantics are owned by:

```text
AGENTS.md
tests/AGENTS.md
docs/testing/repository-governance-contract.md
docs/testing/evidence-authoring-guide.md
docs/testing/current-guarantees.toml
```

## 1. Feature status

The accepted F1 implementation scope is complete in code subject to the final exact-head CI gate:

```text
Organization operational defaults + central public contacts
Location structured operational profile, contacts, hours and exceptions
ResourceLocationAssignment lifecycle
Resource-at-Location recurrence and scoped exceptions
explicit Resource-wide schedule-exception semantic mutation
OfferingVersion base terms + contextual fixed terms
future-effective contextual terms
catalog detail eligible-Location context hints
explicit Resource preference or any eligible Resource in find_slots
aptopt_v2 material observations
contextual find_slots -> book
immutable Reservation commercial commitment + 0..N contextual provenance
CapacityClaim assignment provenance
shared-capacity compatibility
contextual hold/reschedule fail-closed boundary
released aptopt_v1 compatibility
```

No F2-F6 capability is required to close this branch.

## 2. Current test architecture

F1 was implemented while the repository test architecture was being corrected from a release-freeze-oriented layout to guarantee-oriented current-product evidence.

The durable separation is now:

```text
CURRENT PRODUCT
  current source + current Alembic head
  integration + PostgreSQL invariants + production-like E2E

V3 PUBLIC COMPATIBILITY
  current source + frozen V3 public-contract minima

V3 HISTORICAL REPRODUCIBILITY
  released V3 source + released 0001_initial
```

Historical V3 evidence may not require current Request Engine to execute on stale `0001_initial` or retain incidental V3 repository shape.

`tests/integration/f1_operational_profile/` may remain feature-local until PR #75 integrates. Its physical promotion/rename by durable ownership is post-merge cleanup, not a merge blocker. Its guarantees already execute from `scripts/ci/run_current_product.sh`.

## 3. E2E closure correction

During final branch review, one gap was found in the test-architecture migration: `scripts/ci/run_current_product.sh` executed F1 integration and current booking/capacity regression suites but no longer executed `tests/e2e/`.

That would have allowed a false-green current-product gate in which HTTP/runtime journeys silently rotted.

The runner is therefore corrected to execute:

```text
tests/e2e
```

against current Alembic head using the existing production-like E2E framework: real PostgreSQL, RLS/runtime roles, HTTP composition, ActorResolver boundary, transactions and durable-state oracles.

F1 additionally owns contextual E2E scenarios for:

```text
business -> catalog -> contextual find_slots -> aptopt_v2 -> book
catalog offering detail -> only eligible contextual Location hints
find_slots with any eligible Resource vs explicit Resource preference
unknown Resource preference -> opaque empty result
exact CapacityClaim assignment provenance
exact immutable commercial commitment/context source
stale contextual option -> HTTP 409 refresh_and_retry + zero partial effects
contextual reschedule -> HTTP 422 fail-closed + zero mutation
same Resource at two Locations -> distinct schedule/price/duration observations
```

Rejected journeys compare authoritative durable state where mutation safety is the contract; tenant/unknown-ID discovery remains opaque rather than exposing existence.

## 4. Adversarial capability audit and closure

A later adversarial pass intentionally ignored previous green CI and rebuilt the required-capability inventory from docs 13/15. It found three real product-surface gaps that table/schema existence had hidden:

```text
1. Resource-wide schedule_exceptions affected availability and booking,
   but F1 had no supported authority/idempotency/audit command to mutate them.

2. find_slots implemented implicit "any eligible Resource" but no explicit
   Resource preference even though the plan requires explicit/any selection.

3. catalog.get_offering exposed version defaults but no safe Location/context
   hint; callers could not learn where the Offering is contextually eligible.
```

Those gaps are now closed as follows:

```text
SetResourceScheduleExceptionCommand
  -> authority + idempotency + expected Resource availability revision
  -> create/update released schedule_exceptions relation
  -> audit + tenant transaction

FindAppointmentSlotsQuery.resource_id / GET slots?resource_id=...
  -> preference is applied before slot generation and limit
  -> only requirements satisfiable by that Resource are pinned
  -> other multi-resource requirements remain normally resolvable
  -> unknown/foreign IDs remain opaque

OfferingSummary.eligible_location_ids
  -> computed from active Location + all resource requirements
  -> active/effective ResourceLocationAssignment + capability + quantity
  -> no fabricated contextual price before concrete Resource/Location context
  -> omitted on legacy V3 schema to preserve released JSON shape
```

The file-budget guard rejected the first implementation shape because it grew legacy oversized modules. The correction did **not** weaken that guard: candidate loading, catalog mapping/context hints, Resource-wide persistence/codec/audit, API dependencies and E2E fixtures were split into focused modules.

## 5. Adversarial integration evidence

The narrower PostgreSQL/integration suite continues to attack the defects that are expensive or inappropriate to express only through public HTTP:

```text
price/config mutation vs booking
assignment retirement vs booking
Location closure/recurring-hour mutation vs booking
Resource-wide vs assignment-specific exceptions
Resource-wide exception command revision/idempotency semantics
concurrent overlapping context terms/assignments
stale schedule revisions
Offering.active deactivation race
DST gap/fold
foreign/random ID opacity
semantic command authority/idempotency
context-only pricing
multi-resource commercial provenance
shared-capacity contention
historical assignment provenance immutability
```

These are current guarantees, not frozen-V3 shape tests.

## 6. Migration posture

The branch currently introduces `0002_f1_supply` after released `0001_initial`.

That is the F1 migration shape, but **current-product CI no longer hardcodes `0002_f1_supply` as the permanent Request Engine head**. It requires exactly one repository Alembic head, upgrades to `head`, and verifies the database reached that head.

This preserves F1 upgrade/bootstrap evidence without turning the revision name into a future architecture freeze.

## 7. Documentation disposition

Current branch documentation disposition:

```text
13  current implementation/acceptance plan             CURRENT
14  future F2-F6 roadmap                                CURRENT FUTURE DIRECTION
15  normative F1 product/domain contract                CURRENT
16  closed adversarial clarification provenance         HISTORICAL INPUT
17  old->new implementation inventory                   HISTORICAL IMPLEMENTATION EVIDENCE
18  F1 relational-schema explanation                    CURRENT FOR THIS FEATURE
19  greenfield validation-data premise                  CURRENT POLICY INPUT
20  this execution handoff                              CURRENT INFORMATIVE
21  final documentation/evidence audit                  CURRENT INFORMATIVE
```

The repository-wide pre-production/testing policies supersede old statements that treated exact release-era test inventories, migration heads or architecture snapshots as permanent current-product restrictions.

## 8. Remaining merge gates

The branch is merge-ready only when the final PR #75 head satisfies all of the following at the same SHA/merge candidate:

```text
behind development = 0 or explicit reconciliation completed
PR remains mergeable
Python quality + current architecture fitness PASS
current-product PostgreSQL proof PASS
production-like tests/e2e PASS inside current-product proof
new Resource-wide semantic command proof PASS
new explicit Resource preference E2E PASS
new catalog eligible-Location hint E2E PASS
V2 design-history lane PASS
V3 repeated-bootstrap evidence PASS
observability contract PASS
V3 public compatibility + pinned historical provenance PASS
required aggregate PASS
final documentation matches the tested code
no unrelated product scope leakage
```

A previously green SHA does not prove a later documentation/test/code SHA. Any commit after the final successful run requires fresh exact-head evidence.

## 9. ADR disposition

ADR 0012 remains `Proposed` until its acceptance condition is actually met. The implementation and proof may be complete before merge; if the ADR itself requires integration/merge, mark it `Accepted` only after that event rather than predicting it in this branch.
