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
base: 9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

## 3. Capability disposition

| Area | Disposition |
| --- | --- |
| Organization operational profile | COMPLETE / PROVEN |
| canonical Organization public contacts | COMPLETE / PROVEN |
| Location structured profile / contacts / hours / exceptions | COMPLETE / PROVEN |
| ResourceLocationAssignment lifecycle | COMPLETE / PROVEN |
| Resource-at-Location recurrence / scoped exceptions | COMPLETE / PROVEN |
| explicit Resource-wide exception semantic mutation | COMPLETE / PROVEN |
| Base + contextual fixed commercial terms | COMPLETE / PROVEN |
| semantic future-effective contextual-term supersession | COMPLETE / PROVEN |
| catalog detail eligible-Location context hints | COMPLETE / PROVEN |
| explicit Resource or any eligible Resource slot selection | COMPLETE / PROVEN |
| aptopt_v2 contextual observations | COMPLETE / PROVEN |
| contextual direct booking | COMPLETE / PROVEN |
| immutable commercial commitment / 0..N sources | COMPLETE / PROVEN |
| CapacityClaim assignment provenance | COMPLETE / PROVEN |
| cross-tenant shared-capacity compatibility | COMPLETE / PROVEN |
| separate authenticated operational/control-plane HTTP surface | COMPLETE / PROVEN |
| operational HTTP 403/422/409 error semantics | COMPLETE / PROVEN |
| contextual hold | ACCEPTED F1 FAIL-CLOSED |
| contextual reschedule | ACCEPTED F1 FAIL-CLOSED |
| released aptopt_v1 behavior | PRESERVED / REGRESSION-PROTECTED |
| F2-F6 roadmap capabilities | OUT OF THIS BRANCH |

## 4. Adversarial capability-audit findings

The audit deliberately ignored earlier green CI and rebuilt required capability from docs 13/15. It found seven material gaps over two passes:

```text
A. Resource-wide schedule exceptions were consumed by planning/booking but
   had no supported semantic mutation command.

B. find_slots supported implicit "any eligible Resource" but no explicit
   Resource preference.

C. catalog offering detail returned OfferingVersion defaults but no safe
   contextual Location eligibility hint.

D. Future-effective contextual terms were demonstrated by direct SQL mutation
   rather than a supported semantic product path.

E. Administrative /v1/operations routes initially risked becoming part of the
   frozen public API by sharing create_app().

F. Expected operational authority/validation/stale-intent failures lacked a
   complete stable HTTP error contract.

G. Public contact values lacked canonical normalization, allowing equivalent
   endpoints to be represented differently.
```

These were genuine product or evidence-boundary gaps, not naming differences in the schema.

## 5. Findings A-C — original product-surface closure

### A. Resource-wide exception command

Implemented:

```text
SetResourceScheduleExceptionCommand
PostgresResourceScheduleExceptionCommands
booking.set_resource_schedule_exception
```

The supported path owns tenant scoping, operational authority, idempotency/fingerprint replay, expected Resource availability revision, create/update behavior, audit and conflict classification. PostgreSQL proof verifies create, replay, update, revision movement, stale revision rejection and actual availability impact.

### B. Explicit Resource preference

Implemented:

```text
FindAppointmentSlotsQuery.resource_id
GET /v1/appointments/slots?resource_id=<uuid>
```

Selection occurs before contextualization/slot generation/limit. E2E verifies preferred Resource booking persists that Resource claim, while random and real foreign Resource IDs remain the same opaque HTTP 200 empty result.

### C. Catalog contextual Location hints

Implemented optional:

```text
OfferingSummary.eligible_location_ids
OfferingView.eligible_location_ids
```

Eligibility is derived from active Location + all requirements + active matching Resource/capability + active/effective ResourceLocationAssignment + quantity. The API deliberately does not fabricate one contextual amount/duration before concrete context. `None` remains omitted when F1 schema is unavailable, preserving released V3 response shape.

## 6. Findings D-G — deeper closure

### D. Semantic future-term supersession

Implemented:

```text
SupersedeBookingContextTermsCommand
PostgresContextualTermsSupersessionCommands
booking.supersede_booking_context_terms
```

The command performs an atomic effective-date cutover: it validates authority and idempotency, locks current contextual identity/range and governing Resource/assignment, checks the expected revision, closes the current range and inserts the successor in one transaction, then records audit/replay evidence.

`test_contextual_temporal_provenance.py` no longer mutates future contextual configuration with direct SQL. SQL remains there only for observation/provenance and independent database invariants.

### E. Public vs operational HTTP composition roots

Administrative routes are composed through:

```text
create_operational_app()
install_operational_modules()
Tenancy/Catalog/Booking install_operational_http()
```

They are not installed into public `create_app()`. Architecture fitness now proves both composition roots remain separate, HTTP entrypoints reach business modules only through `modules.*.api`, and no entrypoint reaches module adapters.

This closes the risk of making `/v1/operations/*` part of the frozen public operation registry merely by wiring the control-plane into the public app.

### F. Stable operational HTTP error semantics

Expected failures now map through explicit envelopes:

```text
OperationalAuthorityRequired  -> 403 operational_authority_required / request_authority
PublicContactValidationError  -> 422 public_contact_invalid / fix_request
Catalog/Booking conflicts     -> 409 module-specific code / refresh_and_retry
```

No global `ValueError` mapping was introduced.

E2E proves the 403/422/409 behavior through the actual operational app, ActorResolver, Representation checks and PostgreSQL runtime.

### G. Canonical public contacts

Canonicalization is applied before persistence:

```text
phone / whatsapp -> international E.164
email            -> stripped + case-folded canonical form
```

Malformed values are rejected with `PublicContactValidationError`; semantically duplicate canonical endpoints are rejected by executable proof.

## 7. Exact executable evidence

Canonical successful functional checkpoint before this documentation reconciliation:

```text
feature head: 89c1ceaedf54760973018750656d5f38da5a3097
canonical PR CI: 32577169964
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

The Python-quality lane passed:

```text
Python effective line budget
lockfile consistency
Ruff lint
Ruff format
Pyright strict
secret scan
Python security static analysis
dependency vulnerability audit
architecture tests
test-architecture inventory
```

No file-budget limit, ignore or architecture boundary was loosened to obtain green.

The PostgreSQL current-product proof passed:

```text
9 schema/runtime
6 business/catalog/opacity
21 semantic/configuration
21 contextual booking/race/provenance
146 production-like E2E
31 booking/capacity regression
```

The increase from 18 to 21 semantic/configuration tests includes semantic future-term cutover and canonical contact proof. The increase from 144 to 146 E2E adds operational HTTP authority/validation/conflict coverage.

## 8. Retained adversarial guarantees

Current evidence covers:

```text
price/context change vs book
assignment retirement vs book
assignment-specific exception vs book
Resource-wide exception vs book
Resource-wide semantic command lifecycle
Location exception / recurring-hours mutation vs book
Offering.active deactivation vs book
concurrent context-term writes
semantic future contextual-term cutover
concurrent assignment writes
concurrent schedule replacement / stale revision
shared-capacity contention
context-only commercial terms
multi-resource commercial provenance
future-effective term provenance
DST gap/fold
foreign/random ID opacity
semantic authority/idempotency
canonical public contacts
historical assignment provenance immutability
stale option refresh-and-retry
operational HTTP 403/422/409 envelopes
public/control-plane composition separation
contextual reschedule fail-closed
```

## 9. Test architecture disposition

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

The HTTP architecture now has an additional invariant:

```text
PUBLIC RUNTIME                       OPERATIONAL / CONTROL-PLANE RUNTIME
create_app()                         create_operational_app()
install_http()                       install_operational_http()
frozen public operation contract    administrative command surface
```

The two roots share trusted authentication/security primitives but do not silently absorb each other's routes.

## 10. Documentation reconciliation

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

The findings strengthen 13/15 rather than weakening or renaming away their requirements.

## 11. Final pre-merge rule

Run `32577169964` proves the functional checkpoint `89c1ceaedf54760973018750656d5f38da5a3097`. These documentation commits create a later head and must not borrow that status.

Before merge require a fresh exact-head PR run and verify:

```text
latest branch head == PR head
behind development = 0
PR mergeable
all required checks green on exact head
no unresolved review blocker
no accidental F2-F6/product scope leakage
```

Any later commit invalidates that exact-head proof.

## 12. ADR 0012

Keep ADR 0012 `Proposed` until its documented acceptance condition is fulfilled. Because that condition includes integration, do not mark it `Accepted` before merge.
