# Operational Profile & Contextual Supply — Documentation Audit and Reconciliation Matrix

Status: final informative closure/audit record for `feature/operational-profile-contextual-supply`.

This document records what F1 implementation and canonical CI prove. It does **not** create product semantics.

Current F1 sources:

```text
15-operational-profile-contextual-supply-contract.md   normative F1 contract
13-operational-profile-contextual-supply-plan.md       implementation/closure plan
14-operational-intelligence-roadmap.md                 future F2-F6 direction
16-operational-profile-contextual-supply-clarifications.md
                                                       historical audit provenance only
18-operational-profile-contextual-supply-relational-schema.md
                                                       executable-schema reconciliation
20-operational-profile-contextual-supply-implementation-handoff.md
                                                       execution handoff
ADR 0012                                               durable rationale
```

---

## 1. Repository topology

Feature:

```text
feature/operational-profile-contextual-supply
```

Base / merge base with `development` throughout F1 implementation:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

P6 verification confirmed the feature remained:

```text
behind development: 0
```

Final integration vehicle:

```text
PR #75 — Operational profile and contextual supply
base: development
head: feature/operational-profile-contextual-supply
```

PR #75 is intentionally draft until the final exact-head P7 CI/review gate succeeds.

---

## 2. Canonical Phase H proof

The code/proof checkpoint that closed Phase H is:

```text
c1966f04c0b36fbe8b5bc41f85bb69e8a6831503
workflow run: 32516044052
```

Every canonical prerequisite job passed:

| Job | Result |
| --- | --- |
| Python quality and architecture | PASS |
| PostgreSQL 18 F1 operational profile and contextual supply | PASS |
| PostgreSQL 18 V2 design history | PASS |
| PostgreSQL 18 V3 repeated bootstrap proof | PASS |
| Observability runtime contract | PASS |
| PostgreSQL 18 frozen V3 compatibility | PASS |
| PostgreSQL 18 V3 candidate and verticals aggregate | PASS |

The F1 PostgreSQL gate asserts the production Alembic head is exactly:

```text
0002_f1_supply
```

P5 documentation consolidation and P6 cleanup were intentionally performed **after** the Phase H code checkpoint. Therefore the final merge-readiness claim is based on a fresh PR CI run against the final cleaned head, not on `c1966f04...` alone.

Do not edit the branch after the successful P7 exact-head run without requiring a new exact-head run.

---

## 3. Phase disposition

| Phase | Final F1 disposition |
| --- | --- |
| A — documentation/architecture foundation | **COMPLETE** |
| B — old→new inventory | **COMPLETE**; document 17 retained as historical evidence |
| C — relational schema | **COMPLETE + PROVEN**; one unshipped `0002_f1_supply` |
| D — domain/application model | **COMPLETE for accepted F1 scope** |
| E — semantic configuration commands | **COMPLETE for accepted F1 scope** |
| F — deterministic query resolution | **COMPLETE + PROVEN** |
| G — contextual direct booking | **COMPLETE + PROVEN** |
| G — contextual hold/reschedule | **ACCEPTED FAIL-CLOSED F1 SCOPE**; full replacements are future work |
| H — adversarial proof | **COMPLETE** at `c1966f04...` |
| P5 — normative documentation consolidation | **COMPLETE** |
| P6 — repository cleanup | **COMPLETE** |
| P7 — exact-head merge-readiness gate | **external final gate**: PR #75 exact-head CI + final review; any later commit invalidates it |

---

## 4. Commercial provenance blocker — CLOSED

The earlier audit found an obsolete single contextual source field/check that could reject valid context-only pricing.

Final executable model:

```text
reservation_commercial_commitments
  reservation_id
  organization_id
  optional offering_version_booking_terms_id
  committed amount/currency/duration/fingerprint/timestamp

reservation_commercial_commitment_context_terms
  0..N exact contextual source rows
```

The final `reservation_commercial_commitments` table has **no direct `booking_context_terms_id`** and no row-level source-presence CHECK that would forbid context-only pricing.

Canonical proofs cover:

```text
context-only amount/currency with no base-price row
OfferingVersion duration fallback
successful booking
immutable material commitment
exact contextual source preservation
multi-resource 0..N source preservation
no arbitrary primary context
```

---

## 5. Semantic surface gaps — CLOSED

### `CreateLocation`

Dedicated semantic command is implemented and proven:

```text
authorized
idempotent
conflict-safe
tenant-local
structured operational fields
```

Only the expected Location uniqueness conflict is translated as a catalog configuration conflict; unrelated integrity failures remain visible.

### Organization public operational contacts

Dedicated tenancy-owned semantic mutation is implemented and proven:

```text
central Organization endpoints
separate from Location endpoints
separate from PartyContactPoint identity
authorized
idempotent
tenant-local
business.get_info visibility only when public/active
```

### Contextual hold/reschedule

This is no longer an unresolved implementation question.

Accepted F1 boundary:

```text
find_slots -> aptopt_v2 -> book             supported
contextual CapacityHold                      fail closed
contextual Reservation reschedule            fail closed
released aptopt_v1 hold/reschedule            preserved
```

The rejection occurs before a legacy V3 commitment adapter can drop assignment/schedule/commercial provenance.

---

## 6. Offering lifecycle correction — CLOSED

`OfferingVersion` is append-only and is not mutated merely to create a race.

Correct mutable publication/bookability kill-switch:

```text
Offering.active
```

Contextual `find_slots` does not advertise an inactive parent Offering. Contextual `book` locks/revalidates the parent Offering and selected OfferingVersion, so deactivation vs booking serializes deterministically.

---

## 7. Adversarial proof matrix — CLOSED FOR F1

| Scenario | Disposition |
| --- | --- |
| Price change after discovery before book | **PROVEN** stale |
| Assignment retirement after discovery | **PROVEN** stale |
| Location-hours closure after discovery | **PROVEN** stale |
| Assignment-specific exception vs book | **PROVEN** |
| Resource-wide exception vs book | **PROVEN** |
| Recurring Location-hours mutation vs book | **PROVEN** |
| Parent Offering deactivation vs book | **PROVEN** |
| Fresh discovery after Offering deactivation | **PROVEN** absent |
| Concurrent overlapping contextual terms | **PROVEN** serialized/rejected |
| Concurrent overlapping assignments | **PROVEN** serialized/rejected |
| Concurrent schedule replacements | **PROVEN** stale revision guard |
| CapacityClaim assignment provenance rewrite | **PROVEN** impossible through supported mutation |
| Future contextual terms activation | **PROVEN** |
| Future booking exact contextual source | **PROVEN** |
| Context-only commercial booking | **PROVEN** |
| Multi-resource contextual provenance | **PROVEN** every contributor retained |
| Contextual shared-capacity contention | **PROVEN** |
| Contextual hold/reschedule V3 fallthrough | **PROVEN** fail closed |
| `aptopt_v2` reschedule router boundary | **PROVEN** rejected before legacy handler |
| `aptopt_v1` reschedule compatibility | **PROVEN** legacy handler reached |
| Duplicate human-readable identity names | **PROVEN** no authority from name |
| DST spring-forward gap | **PROVEN** explicit rejection |
| DST fall-back fold | **PROVEN** explicit rejection |
| Foreign/random authority IDs | **PROVEN** equivalent rejection |
| Foreign/random Location IDs in discovery | **PROVEN** equally absent |
| Organization contact tenant safety | **PROVEN** |
| CreateLocation tenant/authority safety | **PROVEN** |
| business.get_info safe public truth | **PROVEN** |
| Location/effective-supply catalog filtering | **PROVEN** |
| 13:00–17:00 any-eligible contextual search | **PROVEN** |
| `find_slots -> aptopt_v2 -> decode -> book` | **PROVEN** |
| stale `aptopt_v2` error contract | **PROVEN** HTTP 409 / `appointment_option_stale` / `refresh_and_retry` / no partial Reservation |
| released V3 booking regression | **PROVEN** |
| frozen V3 compatibility | **PROVEN** |

Reopen a row only when later code changes invalidate the proof or a genuinely new falsifying scenario is found.

---

## 8. Capability-flow proof

Canonical F1 CI joins the formerly separate layers into a real application/adapter/database chain:

```text
business.get_info
catalog.search_offerings(Location, effective_at)
appointments.find_slots 13:00-17:00
contextual amount/duration/assignment observation
aptopt_v2 issue/decode
authoritative contextual book
commercial commitment persistence
```

A stale-flow companion changes contextual price after token decode and proves:

```text
AppointmentOptionStale
-> HTTP 409
-> code = appointment_option_stale
-> resolution = refresh_and_retry
-> no Reservation persisted
```

Router proof separately confirms contextual `aptopt_v2` reschedule fails closed while legacy `aptopt_v1` still traverses the released handler.

---

## 9. Documentation reconciliation — COMPLETE

### 15 — normative contract

Closed adversarial findings are folded directly into the F1 contract:

```text
Organization central public contacts
Location-hours exceptions
Resource-wide vs assignment-specific exceptions
Organization != clinic
commercial Offering identity != future workload classification
Offering.active vs immutable OfferingVersion lifecycle
accepted fail-closed contextual hold/reschedule scope
```

### 13 — plan

Current plan already incorporates the closed clarification semantics and final F1 race/acceptance responsibilities.

### 16 — historical clarification record

No longer a higher-precedence F1 amendment. It preserves why the corrections were made and keeps future F2/F3 design questions without creating an amendment maze.

### docs/README

Current F1 precedence is simplified to:

```text
15 > 13 > 14 as future roadmap > released V3 baseline where 15 does not supersede it
```

### 18 — relational schema

Reconciled to executable `0002_f1_supply`, including:

```text
no obsolete direct contextual commercial-source field
0..N append-only contextual provenance bridge
guard_f1_exact_revision_step
final worker privilege revocation
implemented Organization public-contact command
```

### 20 — handoff

Refreshed from obsolete `9d070685...` status to Phase H closure and final P5/P6/P7 workflow.

---

## 10. P6 repository cleanup — COMPLETE

Completed cleanup includes:

```text
removed stale Ruff ignore for nonexistent 0003_f1_commercial_context_sources.py
removed duplicate unit copy of contextual hold/reschedule boundary tests
retained stronger module-level public-command boundary tests
confirmed migrations/versions contains only .gitkeep, 0001_initial.py and 0002_operational_profile_contextual_supply.py
confirmed development and feature use the exact same 0001_initial blob
reviewed V3 freeze adaptations: they pin V3 equivalence to 0001_initial rather than moving head
reviewed V3 public-contract proof: V3 operations/capabilities remain exact while additive post-V3 literal errors are allowed
opened draft PR #75
removed feature-only push CI trigger; pull_request CI is now canonical
```

No adversarial F1 proof was removed merely to reduce file count.

---

## 11. Non-negotiable decisions preserved

```text
0001_initial remains immutable
frozen V3 candidate/design history remains provenance
Resource remains capacity serialization root
CapacityClaim remains capacity ledger
ResourceLocationAssignment is eligibility/context, not capacity
Location closure wins over Resource additional availability
Resource-wide and assignment-specific exceptions are different intent
contextual history never silently restores legacy wildcard Location semantics
price never changes silently during book
historical committed commercial facts are materialized and immutable
contextual CapacityClaims retain assignment provenance
shared-capacity locking remains additive
OfferingVersion remains append-only
Offering.active is mutable parent kill-switch
contextual hold/reschedule never silently degrade to V3
semantic commands remain authoritative configuration surface
F2-F6 scope does not leak into F1
```

---

## 12. P7 exact-head rule

Merge readiness is determined by the **final PR #75 head**, not by this document hard-coding a future run ID.

For the final head require:

```text
branch still current with development (behind_by = 0, or reconcile first)
Alembic head = 0002_f1_supply
Python quality/architecture PASS
F1 PostgreSQL PASS
V2 design history PASS
V3 repeated bootstrap PASS
Observability PASS
frozen V3 compatibility PASS
required aggregate PASS
released V3 booking regressions PASS
no feature-only CI push trigger
no stale provisional F1 migration tooling reference
final diff contains no unrelated product scope
```

The successful GitHub check attached to the final head is the durable P7 evidence. **Any commit after that successful run invalidates P7 and requires another exact-head run.**

ADR 0012 should remain `Proposed` until the proven feature is actually merged; its own acceptance condition intentionally requires proof **and merge**.