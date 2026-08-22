# Operational Profile & Contextual Supply — Documentation and Evidence Audit

Status: current informative closure audit for `feature/operational-profile-contextual-supply`.

This audit does not define product semantics. It reconciles the F1 contract with implementation, current testing policy and merge evidence.

## 1. Sources of truth

Product/domain:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md   normative F1 contract
docs/v3/13-operational-profile-contextual-supply-plan.md       implementation/acceptance plan
docs/v3/14-operational-intelligence-roadmap.md                 F2-F6 future direction
docs/adr/0012-contextual-resource-location-supply.md            durable rationale
```

Testing/repository governance:

```text
AGENTS.md
tests/AGENTS.md
docs/architecture/pre-production-evolution-policy.md
docs/testing/repository-governance-contract.md
docs/testing/evidence-authoring-guide.md
docs/testing/current-guarantees.toml
docs/testing/test-architecture-migration.md
```

Core policy:

```text
freeze the evidence, not the future
```

## 2. Branch topology

Integration vehicle:

```text
PR #75
feature/operational-profile-contextual-supply -> development
```

The feature was based on `development@9665873a90ecbaa52a17b4aff1ec4d1cd4c70573`. Merge readiness always depends on the live compare at review time; an old `behind_by=0` observation is not permanent evidence.

## 3. F1 implementation disposition

| Area | Disposition |
| --- | --- |
| Organization operational profile / central contacts | COMPLETE |
| Location structured profile / contacts / hours / exceptions | COMPLETE |
| ResourceLocationAssignment lifecycle | COMPLETE |
| Resource-at-Location recurrence / scoped exceptions | COMPLETE |
| Base + contextual fixed commercial terms | COMPLETE |
| future-effective contextual terms | COMPLETE |
| aptopt_v2 contextual observations | COMPLETE |
| contextual direct booking | COMPLETE |
| immutable commercial commitment / 0..N sources | COMPLETE |
| CapacityClaim assignment provenance | COMPLETE |
| cross-tenant shared-capacity compatibility | COMPLETE |
| contextual hold | ACCEPTED F1 FAIL-CLOSED |
| contextual reschedule | ACCEPTED F1 FAIL-CLOSED |
| released aptopt_v1 behavior | PRESERVED / REGRESSION-PROTECTED |
| F2-F6 roadmap capabilities | OUT OF THIS BRANCH |

## 4. Important defects closed during implementation

The branch closed several defects/gaps that existed in earlier iterations of the design:

```text
obsolete single contextual commercial-source assumption
missing CreateLocation semantic command
missing Organization central public-contact command
OfferingVersion mutation used incorrectly as lifecycle kill-switch
Offering.active not revalidated by contextual booking
insufficient stale-option race coverage
contextual hold/reschedule could otherwise risk legacy fallthrough
multi-resource contextual provenance lacked explicit proof
```

The current model uses an immutable material commercial commitment plus a 0..N contextual source bridge. `OfferingVersion` remains append-only; `Offering.active` is the mutable parent publication/bookability kill-switch.

## 5. Current test-architecture reconciliation

The test-architecture migration correctly separated historical V3 provenance from current-product evolution. One additional gap was found during this audit:

```text
old migrated current-product runner
  F1 integration + booking/capacity regression
  BUT no tests/e2e
```

That was not acceptable because `tests/e2e/` is explicitly the production-like public/runtime evidence layer.

The current-product runner is corrected to include the full PostgreSQL-marked `tests/e2e` suite against current Alembic head.

This is a KEEP/ADAPT decision under the new policy:

```text
public production-like evidence guarantee    KEEP
historical V3 execution ownership            ADAPT
current-product omission of tests/e2e        REPAIR
```

No historical freeze is being restored.

## 6. F1 E2E proof obligations

The feature-specific production-like journeys now attack the following observable contracts:

### Happy path

```text
GET /v1/business
GET /v1/catalog/offerings?location_id=...&effective_at=...
GET /v1/appointments/slots
  -> contextual amount/currency/duration/location
  -> signed aptopt_v2
POST /v1/appointments
  -> Reservation
  -> active CapacityClaim with exact ResourceLocationAssignment
  -> immutable commercial commitment
  -> exact contextual source bridge
```

### Stale observation

```text
discover option
mutate authoritative contextual price
POST old option
  -> HTTP 409
  -> appointment_option_stale
  -> refresh_and_retry
  -> full authoritative-table snapshot unchanged by rejected request
```

### Unsupported contextual reschedule

```text
book contextual Reservation
obtain contextual replacement option
POST reschedule
  -> HTTP 422
  -> contextual_commitment_unsupported
  -> full authoritative-table snapshot unchanged
```

### Same Resource, two Locations

```text
same Resource
Location A -> schedule A + DOP 4,000 + 45m
Location B -> schedule B + DOP 5,200 + 30m
```

Location-filtered public slot queries must preserve those distinct observations. This directly falsifies accidental assignment/terms conflation rather than relying only on relational cardinality tests.

## 7. Adversarial coverage retained below E2E

Not every important race belongs in a public E2E journey. Current PostgreSQL integration evidence retains targeted proofs for:

```text
price/context change vs book
assignment retirement vs book
assignment-specific exception vs book
Resource-wide exception vs book
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
semantic command authority/idempotency
historical assignment provenance immutability
```

This layered evidence is intentional: E2E proves the composed production-like journey; narrow adversarial tests provide deterministic localization and race control.

## 8. Documentation reconciliation

### 13 — plan

Still semantically correct. It defines F1 scope, acceptance scenarios and adversarial obligations. The new testing policy changes evidence ownership, not F1 product semantics.

### 15 — normative contract

Still semantically correct. In particular, Acceptance A-I remains authoritative. The newly added multi-location E2E explicitly strengthens Acceptance B evidence.

### 16 — clarifications

Historical adversarial-review provenance. It no longer overrides 15/13 after its accepted findings were folded into them.

### 17 — implementation inventory

Historical Phase-B old->new evidence. Do not rewrite it into current status.

### 18 — relational schema

Current explanation of the F1 schema. The branch presently introduces `0002_f1_supply`, but repository-wide current-product CI must not freeze that revision as the permanent future head.

### 20 — handoff

Rewritten to the new current-product / E2E / historical evidence architecture and remaining exact-head gates.

### Testing docs

The repository testing policy is now authoritative for where evidence executes and which structural restrictions may evolve. F1 docs should not duplicate those policies.

## 9. What is not a merge blocker

Under the official migration policy, these items may happen after F1 integrates and are not reasons to keep PR #75 open by themselves:

```text
renaming every V3-era current test whose guarantee remains current
moving every tests/integration/f1_operational_profile file immediately
fully completing the repository-wide proof-map migration for unrelated capabilities
property/state-machine expansion unrelated to F1 acceptance
F2-F6 implementation
```

Feature-era test relocation must preserve evidence but need not be mixed into the feature merge when the canonical current-product gate already owns those guarantees.

## 10. Final exact-head acceptance gate

Do not declare the branch merge-ready from an older successful run.

The final PR head/merge candidate must prove:

```text
Python quality and architecture                         PASS
PostgreSQL current product proof                        PASS
  including tests/e2e                                   PASS
  including F1 integration                              PASS
  including current booking/capacity regressions        PASS
PostgreSQL V2 design history                            PASS
PostgreSQL repeated bootstrap                           PASS
Observability runtime contract                          PASS
V3 public compatibility / pinned historical provenance PASS
required aggregate                                      PASS
```

Additionally:

```text
branch reconciled with current development
PR mergeable
final diff contains no accidental F2-F6/product leakage
documentation describes the tested architecture
```

Any commit after that successful exact-head evidence invalidates the gate and requires another run.

## 11. ADR 0012

Keep `Proposed` until its documented acceptance condition is fulfilled. If the ADR requires both proof and integration, transition it only after merge rather than creating a pre-merge status fiction.
