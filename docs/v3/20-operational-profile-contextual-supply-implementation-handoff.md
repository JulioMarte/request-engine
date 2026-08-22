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
Organization operational defaults + canonical central public contacts
Location structured operational profile, contacts, hours and exceptions
ResourceLocationAssignment lifecycle
Resource-at-Location recurrence and scoped exceptions
explicit Resource-wide schedule-exception semantic mutation
OfferingVersion base terms + contextual fixed terms
future-effective contextual terms through semantic supersession/cutover
catalog detail eligible-Location context hints
explicit Resource preference or any eligible Resource in find_slots
aptopt_v2 material observations
contextual find_slots -> book
immutable Reservation commercial commitment + 0..N contextual provenance
CapacityClaim assignment provenance
shared-capacity compatibility
separate authenticated operational/control-plane HTTP composition root
machine-readable operational HTTP authority/validation/conflict semantics
contextual hold/reschedule fail-closed boundary
released aptopt_v1 compatibility
```

No F2-F6 capability is required to close this branch.

## 2. Adversarial capability audit

A capability-first audit intentionally ignored earlier green CI and rebuilt the required inventory from docs 13/15. The first pass found three product-surface gaps:

```text
A. Resource-wide schedule_exceptions affected availability and booking,
   but there was no supported semantic mutation command.

B. find_slots supported implicit "any eligible Resource" but no explicit
   Resource preference.

C. catalog offering detail exposed version defaults but no safe contextual
   Location-eligibility hint.
```

All three were implemented and proven. A deeper closure pass then found four additional integration-quality gaps:

```text
D. Future-effective contextual terms were proven with direct SQL mutation
   instead of the supported product path.

E. Administrative /v1/operations routes risked becoming part of the frozen
   public API when composed into create_app().

F. Expected operational authority, validation and stale-configuration errors
   could escape without stable HTTP semantics.

G. Public contact values lacked one canonical representation, allowing
   semantically duplicate phone/WhatsApp/email endpoints.
```

All four are now closed without weakening file-budget, architecture or compatibility guards.

## 3. Closure details

### Resource-wide semantic exception mutation

`SetResourceScheduleExceptionCommand` and its PostgreSQL adapter provide tenant authority, idempotency, expected Resource availability revision, create/update behavior over released `schedule_exceptions`, audit and opaque conflict handling.

The initial implementation exceeded repository file budgets. The guard was not weakened; persistence, codec and audit responsibilities were separated into focused modules.

### Explicit Resource preference

`FindAppointmentSlotsQuery.resource_id` and `GET /v1/appointments/slots?resource_id=...` support explicit Resource preference before contextualization, slot generation and limit. Unknown and foreign-tenant Resource IDs remain equally opaque. Multi-resource requirements not satisfied by the preferred Resource remain normally resolvable.

### Catalog contextual Location hints

Offering detail exposes optional `eligible_location_ids` derived from active Location, all OfferingVersion resource requirements, matching active Resources/capabilities, active/effective ResourceLocationAssignments and required quantity. It does not fabricate a contextual price before concrete context exists. The field is omitted when F1 schema is unavailable, preserving released V3 JSON shape.

### Semantic future-term supersession

Future-effective contextual terms now use `SupersedeBookingContextTermsCommand` rather than direct test SQL. The command path owns:

```text
tenant transaction
authority
idempotency + request fingerprint
expected current revision
Resource / assignment locking
atomic old-range cutover + successor insertion
audit + replay result
overlap/conflict classification
```

The temporal provenance test now uses this product path and retains SQL only for observation/evidence.

### Canonical public contacts

Public contact input is canonicalized before persistence:

```text
phone / whatsapp -> international E.164
email            -> stripped + case-folded canonical address
```

Invalid values produce a typed validation error and canonical duplicates are rejected.

### Separate operational HTTP composition root

Administrative routes are not installed into the public `create_app()` surface. They are composed through `create_operational_app()` with module-owned `install_operational_http()` installers for Tenancy, Catalog and Booking.

Architecture fitness tests now enforce:

```text
public app does not compose operational_composition
operational app does not compose module_composition
HTTP entrypoints may reach modules only through modules.*.api
entrypoints never reach module adapters
operational installers remain module-owned connection surfaces
```

This preserves the frozen public operation registry rather than expanding it merely to make tests green.

### Operational HTTP error semantics

Expected control-plane failures now have stable machine-readable envelopes:

```text
403 operational_authority_required -> request_authority
422 public_contact_invalid          -> fix_request
409 module revision/config conflict -> refresh_and_retry
```

The implementation intentionally does not catch `ValueError` globally, so programming defects are not misclassified as caller errors.

## 4. Current-product evidence

Canonical successful functional checkpoint before this documentation reconciliation:

```text
feature head: 89c1ceaedf54760973018750656d5f38da5a3097
PR CI run:   32577169964
```

That exact run passed:

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
21 semantic/configuration tests
21 contextual booking/race/provenance tests
146 production-like E2E tests
31 current booking/capacity regression tests
```

Notable explicit proofs include:

```text
Resource-wide semantic exception lifecycle
explicit Resource preference + unknown/foreign opacity + persisted preferred claim
catalog offering detail eligible contextual Locations
semantic future-term supersession + temporal source provenance
canonical duplicate public-contact rejection
operator HTTP 403/422/409 behavior through runtime PostgreSQL
public/operator composition-root separation
multi-resource and context-only commercial provenance
shared-capacity contention
configuration-vs-book races
DST gap/fold
Offering deactivation race
stale contextual option refresh-and-retry
contextual reschedule fail-closed
```

The E2E suite increased from 144 to 146 because the operational HTTP surface now has production-like authority/validation/conflict coverage.

## 5. Test architecture

The durable evidence model remains:

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

## 6. File-budget and static-quality closure

No file-budget limit, ignore or architecture guard was loosened. The final functional checkpoint passed:

```text
Python effective line budget
Ruff lint
Ruff format
Pyright strict
secret scan
Python security static analysis
dependency vulnerability audit
architecture tests
test architecture/evidence inventory
```

Where new responsibilities would have grown oversized modules, they were split into focused files rather than exempted.

## 7. Integration state

At the functional checkpoint:

```text
base development: 9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
PR #75 mergeable: true
```

This documentation reconciliation creates a later head. Therefore the run above is evidence for the implementation, not permission to borrow green status for the documentation-inclusive head.

## 8. Documentation disposition

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

## 9. Remaining pre-merge gate

After these documentation commits require a fresh exact-head PR run and verify:

```text
latest branch head == PR head
behind development = 0
PR mergeable
all required PR jobs PASS on that exact head
no unresolved review blocker
no accidental F2-F6/product scope leakage
ADR 0012 remains Proposed until its documented integration condition is met
```

Any later commit invalidates the exact-head proof and requires a new run.
