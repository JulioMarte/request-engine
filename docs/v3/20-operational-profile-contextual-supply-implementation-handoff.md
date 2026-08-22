# Operational Profile & Contextual Supply — Implementation Handoff

Status: implementation-complete pre-merge handoff for `feature/operational-profile-contextual-supply`.

This document is informative status/evidence guidance. Product semantics remain owned by:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Testing/evidence semantics are owned by repository testing governance.

## 1. Feature status

The accepted F1 implementation scope is complete in code:

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

## 2. Adversarial capability audit

A capability-first audit intentionally ignored earlier green CI and rebuilt the required inventory from docs 13/15. It found three real gaps that schema/table existence had hidden:

```text
1. Resource-wide schedule_exceptions affected availability and booking,
   but there was no supported semantic mutation command.

2. find_slots supported implicit "any eligible Resource" but no explicit
   Resource preference.

3. catalog offering detail exposed version defaults but no safe contextual
   Location-eligibility hint.
```

All three are now implemented.

### Resource-wide semantic exception mutation

`SetResourceScheduleExceptionCommand` and its PostgreSQL adapter provide:

```text
tenant transaction
authority check
idempotency
expected Resource availability revision
create/update of released schedule_exceptions
audit record
opaque tenant-safe rejection
```

The initial implementation exceeded repository file budgets. The guard was not weakened; persistence, codec and audit responsibilities were separated into focused modules.

### Explicit Resource preference

`FindAppointmentSlotsQuery.resource_id` and `GET /v1/appointments/slots?resource_id=...` now support explicit provider/Resource preference.

The preference is applied before contextualization, slot generation and limit so the planner cannot produce a false empty result after generating slots for another eligible Resource. Multi-resource requirements that the selected Resource does not satisfy remain normally resolvable.

Unknown and foreign-tenant Resource IDs produce the same opaque empty discovery result.

### Catalog contextual Location hints

Offering detail now exposes optional `eligible_location_ids` computed from:

```text
active Location
all OfferingVersion resource requirements
active Resource with matching capability
active/effective ResourceLocationAssignment
required quantity
```

It does not fabricate one contextual price before a concrete Resource/Location context exists. The field is omitted when F1 schema is unavailable, preserving released V3 JSON shape.

## 3. Current-product evidence

Canonical successful adversarial closure checkpoint before this documentation-only reconciliation:

```text
feature head: ea899e70060441d9247a4226d6949ae6773ca095
PR CI run:   32569661743
```

That run passed:

```text
Python quality and architecture                         PASS
PostgreSQL 18 current product proof                      PASS
PostgreSQL 18 V2 design history                          PASS
PostgreSQL 18 V3 repeated bootstrap proof                PASS
Observability runtime contract                           PASS
PostgreSQL 18 frozen V3 compatibility                    PASS
PostgreSQL 18 V3 candidate and verticals aggregate       PASS
```

The current-product proof included:

```text
9 schema/runtime tests
6 business/catalog/opacity tests
18 semantic/configuration tests
21 contextual booking/race/provenance tests
144 production-like E2E tests
31 current booking/capacity regression tests
```

Notable explicit proofs include:

```text
Resource-wide semantic command create/update/idempotency/revision behavior
explicit Resource preference + unknown/foreign opacity + booked preferred claim
catalog offering detail includes only eligible contextual Locations
multi-resource contextual commercial provenance
context-only commercial terms
shared-capacity contention
config-vs-book races
DST gap/fold
Offering deactivation race
stale contextual option refresh-and-retry
contextual reschedule fail-closed
```

## 4. Test architecture

The durable evidence model is:

```text
CURRENT PRODUCT
  current source + current Alembic head
  integration + PostgreSQL invariants + production-like E2E

V3 PUBLIC COMPATIBILITY
  current source + frozen V3 public-contract minima

V3 HISTORICAL REPRODUCIBILITY
  released V3 source + released 0001_initial
```

`scripts/ci/run_current_product.sh` executes the PostgreSQL-marked E2E suite in addition to F1 integration and current booking/capacity regression evidence. Historical V3 proof is pinned separately and does not freeze current architecture.

## 5. File-budget correction

The first adversarial fixes were rejected by the Python effective-line budget because they grew legacy oversized modules. We did not increase limits or add ignores.

Responsibilities were extracted into focused modules including:

```text
booking/adapters/db/candidate_source.py
booking/adapters/db/resource_schedule_exception_store.py
booking/adapters/db/resource_schedule_exception_codec.py
booking/adapters/db/resource_schedule_exception_audit.py
catalog/adapters/db/contextual_location_hints.py
catalog/adapters/db/offering_mapping.py
catalog/api/offering_models.py
tests/e2e/contextual_resource_support.py
```

The final Python-quality checkpoint passed file budget, Ruff, formatting, Pyright, security/static checks, architecture tests and unit/module tests.

## 6. Integration state

At the adversarial closure checkpoint:

```text
base development: 9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
behind development: 0
PR #75 mergeable: true
```

This documentation reconciliation creates a later head, so the repository rule remains: do not call the branch merge-ready until PR CI is green on that exact later head as well.

## 7. Documentation disposition

```text
13  implementation/acceptance plan                     CURRENT
14  F2-F6 roadmap                                      CURRENT FUTURE DIRECTION
15  normative F1 product/domain contract               CURRENT
16  closed adversarial clarification provenance        HISTORICAL INPUT
17  old->new implementation inventory                  HISTORICAL IMPLEMENTATION EVIDENCE
18  F1 relational-schema explanation                   CURRENT FOR THIS FEATURE
19  greenfield validation-data premise                 CURRENT POLICY INPUT
20  this implementation handoff                        CURRENT INFORMATIVE
21  documentation/evidence closure audit               CURRENT INFORMATIVE
```

## 8. Remaining pre-merge gate

Only exact-head evidence remains after any documentation-only reconciliation:

```text
latest branch head == PR head
behind development = 0
PR mergeable
all required PR jobs PASS on that exact head
no accidental scope leakage
ADR 0012 remains Proposed until its documented integration condition is met
```

Any commit after the final successful run invalidates the evidence and requires a fresh exact-head run.
