# Operational Profile & Contextual Supply — Documentation and Evidence Audit

Status: current informative closure audit for `feature/operational-profile-contextual-supply`.

This audit does not define product semantics. It reconciles the normative F1 contract with implementation and executable evidence.

## 1. Sources of truth

Product/domain:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md   normative F1 contract
docs/v3/13-operational-profile-contextual-supply-plan.md       implementation/acceptance plan
docs/v3/14-operational-intelligence-roadmap.md                 F2-F6 future direction
docs/adr/0012-contextual-resource-location-supply.md            durable rationale
```

Testing/repository governance remains owned by `AGENTS.md`, `tests/AGENTS.md` and `docs/testing/*`.

Core policy:

```text
freeze the evidence, not the future
```

## 2. Integration vehicle

```text
PR #75
feature/operational-profile-contextual-supply -> development
```

The feature base remains:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

At the last verified compare before this documentation-only reconciliation:

```text
behind development: 0
PR mergeable: true
```

## 3. Capability disposition

| Area | Disposition |
| --- | --- |
| Organization operational profile / central contacts | COMPLETE |
| Location structured profile / contacts / hours / exceptions | COMPLETE |
| ResourceLocationAssignment lifecycle | COMPLETE |
| Resource-at-Location recurrence / scoped exceptions | COMPLETE |
| explicit Resource-wide exception semantic mutation | COMPLETE / PROVEN |
| Base + contextual fixed commercial terms | COMPLETE / PROVEN |
| future-effective contextual terms | COMPLETE / PROVEN |
| catalog detail eligible-Location context hints | COMPLETE / PROVEN |
| explicit Resource or any eligible Resource slot selection | COMPLETE / PROVEN |
| aptopt_v2 contextual observations | COMPLETE / PROVEN |
| contextual direct booking | COMPLETE / PROVEN |
| immutable commercial commitment / 0..N sources | COMPLETE / PROVEN |
| CapacityClaim assignment provenance | COMPLETE / PROVEN |
| cross-tenant shared-capacity compatibility | COMPLETE / PROVEN |
| contextual hold | ACCEPTED F1 FAIL-CLOSED |
| contextual reschedule | ACCEPTED F1 FAIL-CLOSED |
| released aptopt_v1 behavior | PRESERVED / REGRESSION-PROTECTED |
| F2-F6 roadmap capabilities | OUT OF THIS BRANCH |

## 4. Adversarial capability audit findings

A later audit deliberately ignored previous green CI and rebuilt the required-capability inventory from docs 13/15. It found three product-surface gaps:

```text
A. Resource-wide schedule exceptions were consumed by planning/booking but
   had no supported semantic mutation command; tests used direct SQL.

B. find_slots supported implicit "any eligible Resource" but no explicit
   Resource preference.

C. catalog offering detail returned OfferingVersion defaults but no safe
   contextual Location eligibility hints.
```

These were genuine missing capabilities, not naming differences in the database.

## 5. Finding A — Resource-wide exception command

Implemented:

```text
SetResourceScheduleExceptionCommand
PostgresResourceScheduleExceptionCommands
booking.set_resource_schedule_exception
```

The supported path now owns:

```text
tenant scoping
operational authority
idempotency + fingerprint replay
expected Resource availability revision
create/update of released request_engine.schedule_exceptions
audit trail
conflict classification
```

The adversarial PostgreSQL proof verifies create, replay, update, revision movement, stale-revision rejection and actual availability impact.

The initial adapter exceeded the repository hard file budget. The budget was not weakened. Persistence, state codec and audit were separated into dedicated modules.

## 6. Finding B — explicit Resource preference

Implemented:

```text
FindAppointmentSlotsQuery.resource_id
GET /v1/appointments/slots?resource_id=<uuid>
```

Selection is applied before contextualization/slot generation/limit. This prevents a post-filter false-negative where the planner could generate its limit from other Resources before checking the preferred Resource.

The E2E proof verifies:

```text
no resource_id -> any eligible Resource remains possible
preferred Resource -> returned options use the preferred Resource
preferred Resource contextual price is preserved
booking the preferred option persists only that Resource claim
random Resource ID -> HTTP 200 []
foreign-tenant Resource ID -> same opaque HTTP 200 []
```

For multi-requirement Offerings, only requirements satisfiable by the preferred Resource are pinned; unrelated requirements remain normally resolvable.

## 7. Finding C — catalog contextual Location hints

Implemented optional:

```text
OfferingSummary.eligible_location_ids
OfferingView.eligible_location_ids
```

Eligibility is derived from:

```text
active Location
OfferingVersion resource requirements
active matching Resources
matching capabilities
effective active ResourceLocationAssignments
required quantity
```

The detail API intentionally does not fabricate a single contextual amount/duration because those values may differ by Resource and Location.

E2E verifies that the actual contextual clinic is returned and an active but unassigned Location is excluded.

The field is optional and `None` is omitted by the API when F1 schema is unavailable, preserving the released V3 response shape.

## 8. Exact executable evidence

The adversarial closure checkpoint before the final documentation-only commits is:

```text
feature head: ea899e70060441d9247a4226d6949ae6773ca095
canonical PR CI: 32569661743
```

Every required job passed:

```text
Python quality and architecture                         PASS
PostgreSQL 18 current product proof                      PASS
PostgreSQL 18 V2 design history                          PASS
PostgreSQL 18 V3 repeated bootstrap proof                PASS
Observability runtime contract                           PASS
PostgreSQL 18 frozen V3 compatibility                    PASS
PostgreSQL 18 V3 candidate and verticals aggregate       PASS
```

The Python-quality lane explicitly passed:

```text
Python effective line budget
lockfile consistency
Ruff lint
Ruff format
Pyright
secret scan
security static analysis
dependency vulnerability audit
architecture tests
unit tests
module tests
test-architecture inventory
```

No file-budget limit or ignore was loosened to obtain green.

The PostgreSQL current-product proof passed:

```text
9 schema/runtime
6 business/catalog/opacity
18 semantic/configuration
21 contextual booking/race/provenance
144 production-like E2E
31 booking/capacity regression
```

## 9. Important retained adversarial guarantees

Current evidence continues to cover:

```text
price/context change vs book
assignment retirement vs book
assignment-specific exception vs book
Resource-wide exception vs book
Resource-wide semantic command lifecycle
Location exception / recurring-hours mutation vs book
Offering.active deactivation vs book
concurrent context-term writes
concurrent assignment writes
concurrent schedule replacement / stale revision
shared-capacity contention
context-only commercial terms
multi-resource commercial provenance
future-effective terms
DST gap/fold
foreign/random ID opacity
semantic authority/idempotency
historical assignment provenance immutability
stale option refresh-and-retry
contextual reschedule fail-closed
```

## 10. Test architecture disposition

The durable separation remains:

```text
CURRENT PRODUCT
  current source + current Alembic head
  current integration + PostgreSQL invariants + production-like E2E

V3 PUBLIC COMPATIBILITY
  current source + released V3 public minima

V3 HISTORICAL REPRODUCIBILITY
  released V3 source + released 0001_initial
```

`scripts/ci/run_current_product.sh` includes `tests/e2e`; therefore HTTP/runtime journeys cannot silently disappear from current-product proof.

The adversarial fixes also validated the file-budget architecture policy. New responsibilities were extracted instead of expanding already oversized modules.

## 11. Documentation reconciliation

```text
13  current implementation/acceptance plan             CURRENT
14  future F2-F6 roadmap                                CURRENT FUTURE DIRECTION
15  normative F1 product/domain contract                CURRENT
16  closed clarification provenance                     HISTORICAL INPUT
17  old->new inventory                                  HISTORICAL IMPLEMENTATION EVIDENCE
18  F1 relational schema explanation                    CURRENT FOR F1
19  greenfield validation-data premise                  CURRENT POLICY INPUT
20  implementation handoff                              CURRENT INFORMATIVE
21  this audit                                          CURRENT INFORMATIVE
```

The adversarial findings strengthen 13/15 rather than weakening or renaming away their requirements.

## 12. Final pre-merge rule

The successful run above proves `ea899e70060441d9247a4226d6949ae6773ca095`. The documentation reconciliation itself creates a later commit, so it must not borrow that green status.

Before merge, require a fresh PR run where all required jobs are green on the latest documentation-inclusive branch head, then verify:

```text
latest branch head == PR head
behind development = 0
PR mergeable
no accidental F2-F6/product scope leakage
all required checks green on exact head
```

Any later commit invalidates that exact-head proof.

## 13. ADR 0012

Keep ADR 0012 `Proposed` until its documented acceptance condition is fulfilled. Because that condition includes integration, do not mark it `Accepted` before merge.
