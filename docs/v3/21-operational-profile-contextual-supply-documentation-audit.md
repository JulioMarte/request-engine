# Operational Profile & Contextual Supply — Documentation Audit and Reconciliation Matrix

Status: current informative closure/audit record for `feature/operational-profile-contextual-supply`.

This document records what the F1 implementation and canonical CI have actually proven. It does **not** create product semantics; the normative contract is `15-operational-profile-contextual-supply-contract.md`, with the implementation plan in `13-operational-profile-contextual-supply-plan.md` and durable rationale in ADR 0012.

---

## 1. Repository state and evidence checkpoint

Feature branch:

```text
feature/operational-profile-contextual-supply
```

Feature base / merge base with `development`:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

Latest compare during this audit:

```text
ahead of development: 260 commits
behind development: 0 commits
```

The exact code/proof checkpoint that closes Phase H is:

```text
c1966f04c0b36fbe8b5bc41f85bb69e8a6831503
workflow run: 32516044052
```

Every canonical prerequisite job on that SHA completed successfully:

| Job | Result |
| --- | --- |
| Python quality and architecture | PASS |
| PostgreSQL 18 F1 operational profile and contextual supply | PASS |
| PostgreSQL 18 V2 design history | PASS |
| PostgreSQL 18 V3 repeated bootstrap proof | PASS |
| Observability runtime contract | PASS |
| PostgreSQL 18 frozen V3 compatibility | PASS |
| PostgreSQL 18 V3 candidate and verticals aggregate | PASS |

The F1 PostgreSQL job also asserts the production Alembic head is exactly:

```text
0002_f1_supply
```

Documentation-only consolidation continued after that proven code checkpoint. Therefore `c1966f04...` is the canonical Phase H implementation proof, while a **fresh exact-head CI run remains required after P5/P6 documentation and repository cleanup** before merge readiness.

---

## 2. Phase disposition

### Phase A — documentation/architecture foundation

**COMPLETE**, subject only to final consolidation/cleanup of the temporary clarification chain.

### Phase B — old→new implementation inventory

**COMPLETE.** `17-operational-profile-contextual-supply-implementation-inventory.md` remains historical Phase B evidence and should not be rewritten as current status.

### Phase C — relational schema

**COMPLETE and proven.** F1 is one unshipped post-baseline Alembic revision:

```text
0001_initial
  -> 0002_f1_supply
```

The released V3 baseline, frozen candidate and design-chain history remain immutable provenance.

### Phase D — domain/application model

**COMPLETE for accepted F1 scope.** The implementation has concrete application/domain/contracts for Organization/Location operational profile, contextual supply, assignment lifecycle, contextual terms and appointment option observations.

### Phase E — semantic configuration commands

**COMPLETE for accepted F1 scope.** The previously missing semantic responsibilities now exist, including:

```text
CreateLocation
UpdateOrganizationOperationalProfile
SetOrganizationPublicContacts
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

Commands are covered by authority, idempotency, stale-intent/revision behavior where applicable, tenant/RLS boundaries and audit semantics.

### Phase F — query resolution

**COMPLETE and proven for F1.** `business.get_info`, catalog Location/effective-supply filtering and contextual appointment availability resolve from Request Engine operational truth without CMS/RAG dependency.

### Phase G — contextual booking integration

**COMPLETE for accepted F1 scope.** The authoritative path is:

```text
find_slots
  -> contextual AppointmentSlot
  -> aptopt_v2
  -> decode
  -> contextual book
  -> CapacityClaim + immutable commercial commitment + provenance
```

Legacy `aptopt_v1` behavior remains compatible.

### Phase H — adversarial proof

**COMPLETE at `c1966f04...` / run `32516044052`.** The code, schema, race, authority, DST, tenant-opacity, compatibility and capability-flow proofs described below all execute inside canonical CI.

---

## 3. Commercial provenance blocker — CLOSED

The earlier audit found that a valid context-only price could be resolved while the old row-level commitment source check still required a direct source column that the multi-source writer no longer populated.

That blocker is closed.

The accepted model is now:

```text
reservation_commercial_commitments
  committed amount/currency/duration/fingerprint
  optional OfferingVersion base-term source

reservation_commercial_commitment_context_terms
  0..N exact contextual source rows
```

There is no arbitrary single “primary” contextual term.

Canonical proof includes:

```text
context-only amount/currency
+
no OfferingVersion base-price row
+
OfferingVersion duration
-> discoverable
-> bookable
-> immutable commitment persisted
-> exact contextual source preserved
```

Multi-resource contextual provenance preserves every contextual contributor rather than collapsing provenance into one source.

---

## 4. Semantic-surface gaps — CLOSED

### 4.1 `CreateLocation`

A dedicated semantic command/adapter now exists and is proven:

```text
authorized
idempotent
conflict-safe
tenant-local
structured operational fields
```

A duplicate `location_key` is translated only for the expected Location conflict; unrelated integrity failures are not hidden as generic configuration conflicts.

### 4.2 Organization public operational contacts

A dedicated tenancy-owned semantic mutation now exists and is proven:

```text
central Organization contact endpoints
separate from Location contacts
separate from PartyContactPoint identity
authorized
idempotent
tenant-local
readable through business.get_info
```

### 4.3 Contextual hold/reschedule disposition

This is no longer an open F1 decision.

Accepted F1 scope is:

```text
contextual find_slots -> aptopt_v2 -> book    SUPPORTED
contextual CapacityHold                       FAIL CLOSED
contextual Reservation reschedule             FAIL CLOSED
released aptopt_v1 commitment paths           PRESERVED
```

Fail-closed is required before a released-V3 adapter can discard assignment/schedule/commercial provenance. Full contextual hold/reschedule replacement flows are a future feature, not hidden unfinished F1 work.

---

## 5. Adversarial matrix — CLOSED FOR F1

| Scenario | Disposition / proof |
| --- | --- |
| Price changes after discovery before book | **PROVEN** by deterministic PostgreSQL race; stale option rejected |
| Assignment retires after discovery before book | **PROVEN** by deterministic PostgreSQL race |
| Location-hours exception closes slot before book | **PROVEN** |
| Assignment-specific schedule exception vs book | **PROVEN**; booking serializes/revalidates and fails stale |
| Resource-wide exception vs book | **PROVEN**; booking serializes/revalidates and fails stale |
| Recurring Location-hours mutation vs book | **PROVEN** |
| Parent Offering deactivated after discovery | **PROVEN**; Offering is mutable kill-switch, OfferingVersion remains append-only |
| Fresh discovery after Offering deactivation | **PROVEN**; inactive Offering is not advertised |
| Concurrent overlapping contextual-term writes | **PROVEN** using a real PostgreSQL lock barrier; exactly one overlapping write survives |
| Concurrent overlapping assignment writes | **PROVEN** using a real PostgreSQL lock barrier; exactly one overlapping write survives |
| Concurrent schedule replacement | **PROVEN** by Resource availability revision stale-intent guard |
| Existing CapacityClaim assignment provenance cannot be rewritten | **PROVEN** |
| Future contextual terms activate at boundary | **PROVEN** |
| Future booking preserves exact contextual source | **PROVEN** |
| Context-only price with no base terms can book | **PROVEN** |
| Multi-source contextual commercial provenance | **PROVEN** |
| Contextual shared-capacity contention | **PROVEN**; contextual configuration does not bypass global/shared capacity |
| Contextual hold/reschedule cannot fall into V3 semantics | **PROVEN** fail-closed at commitment boundary |
| `aptopt_v2` contextual reschedule router path | **PROVEN** fail-closed before legacy handler |
| `aptopt_v1` legacy reschedule router path | **PROVEN** still reaches released handler |
| Duplicate human-readable Party names cannot grant authority | **PROVEN** |
| Contextual DST spring-forward gap | **PROVEN** explicit rejection |
| Contextual DST fall-back fold | **PROVEN** explicit rejection |
| Foreign/random authority IDs | **PROVEN** observationally equivalent rejection on new semantic writes |
| Foreign/random Location IDs in catalog/find_slots | **PROVEN** equally absent; no cross-tenant existence oracle |
| Organization public-contact mutation tenant safety | **PROVEN** |
| CreateLocation tenant/authority safety | **PROVEN** |
| `business.get_info` exposes typed public operational truth only | **PROVEN**; non-public central contact excluded |
| Location/effective-supply catalog filtering | **PROVEN** |
| 13:00–17:00 contextual slot search, any eligible Resource | **PROVEN** |
| `find_slots -> aptopt_v2 -> decode -> book` | **PROVEN** end-to-end at application/adapters/DB boundary |
| stale `aptopt_v2` machine-readable result | **PROVEN** HTTP 409, `appointment_option_stale`, `refresh_and_retry`, no partial Reservation |
| Released V3 booking regression | **PROVEN** in F1 runner and frozen-V3 compatibility job |

Phase H must not be reopened merely because the older audit text once listed these as gaps. Reopen an item only if code changes invalidate its proof or a new falsifying scenario is discovered.

---

## 6. Correct Offering lifecycle interpretation

An earlier race row incorrectly described “OfferingVersion becomes inactive”. That is impossible in the accepted implementation because `OfferingVersion` is append-only.

The correct state model is:

```text
OfferingVersion
  immutable/versioned commercial-booking definition

Offering.active
  mutable parent-level publication/availability kill-switch
```

`find_slots` requires the parent Offering to be active. Contextual `book` locks/revalidates both the parent Offering and selected OfferingVersion, so Offering deactivation and booking cannot cross without deterministic serialization.

Do not weaken OfferingVersion immutability to create a mutable-state race.

---

## 7. Capability-flow proof added during closure

The canonical F1 runner now executes `test_capability_flow.py`, which joins previously separate proofs into one real chain:

```text
business.get_info
catalog.search_offerings(Location, effective_at)
appointments.find_slots 13:00-17:00
contextual amount/duration/assignment observation
aptopt_v2 issue/decode
authoritative contextual book
commercial commitment persistence
```

A companion stale flow mutates current contextual price after decoding the option and proves:

```text
AppointmentOptionStale
-> HTTP 409
-> code = appointment_option_stale
-> resolution = refresh_and_retry
-> no Reservation persisted
```

Module/router proof separately confirms `aptopt_v2` contextual reschedule fails closed before the legacy handler while `aptopt_v1` still reaches it.

---

## 8. Documentation reconciliation status

### `15-operational-profile-contextual-supply-contract.md`

Closed F1 clarifications have now been folded into the main contract, including:

```text
Organization central public contacts
Location-hours exceptions
Resource-wide vs Resource-at-Location exceptions
Organization != clinic
commercial Offering identity != future live workload classification
Offering.active vs immutable OfferingVersion lifecycle
accepted fail-closed contextual hold/reschedule scope
```

### `16-operational-profile-contextual-supply-clarifications.md`

Its F1 correction role is now historical because those closed F1 decisions have been folded into `15`. Its F2/F3 future design questions remain useful roadmap input until moved/linked to their owning future feature documents.

### `13-operational-profile-contextual-supply-plan.md`

Still requires final wording reconciliation so its Phase H/race terminology matches the now-proven implementation and the parent `Offering.active` lifecycle. It remains a plan/history document rather than the source for present-tense proof status.

### `18-operational-profile-contextual-supply-relational-schema.md`

Must continue matching executable `0002_f1_supply`; the executable migration wins if any discrepancy is found.

### `20-operational-profile-contextual-supply-implementation-handoff.md`

Must be refreshed after P5/P6 so the next session starts from the final exact implementation/proof checkpoint rather than the obsolete `9d070685...` state.

### ADR 0012

Remain `Proposed` until P6 cleanup and P7 exact-head merge-readiness proof are complete. Phase H success alone is not sufficient to mark the architecture accepted into `development`.

---

## 9. Remaining work after Phase H

P0 through P4 of the previous continuation plan are complete.

### P5 — normative-document consolidation — IN PROGRESS

Required closure:

```text
15: closed F1 clarifications folded in                    DONE
13: reconcile closed clarification/race terminology       TODO
16: demote F1 amendment role; preserve future F2/F3 notes TODO
docs/README: simplify current F1 precedence               TODO
18/20/21: final factual reconciliation                    21 DONE, 18/20 TODO
```

### P6 — repository cleanup — TODO

At minimum:

```text
remove feature-only push trigger from ci.yml
remove stale Ruff ignore for nonexistent 0003 F1 migration
review temporary/duplicate tests or tooling
verify no obsolete provisional F1 migration references remain
verify frozen V3/release provenance files remain unchanged
```

Do not remove F1 tests merely to shrink the branch; retain proofs that protect real invariants.

### P7 — exact-head merge readiness — TODO

On the final cleaned head:

```text
compare against development
require behind_by = 0 or reconcile development
require Alembic head = 0002_f1_supply
run full canonical CI
inspect every prerequisite job, not only aggregate
prove frozen V3 compatibility
prove F1 contextual suite
prove released V3 regressions
verify no temporary feature-only CI trigger remains
review final diff for accidental scope leakage
```

Only after P7 may ADR 0012 be considered for `Accepted` and the feature be called merge-ready.

---

## 10. Non-negotiable decisions to preserve

```text
0001_initial remains immutable
frozen V3 candidate/design history remains immutable
Resource remains the capacity serialization root
CapacityClaim remains the capacity ledger
ResourceLocationAssignment is eligibility/configuration, not capacity
Location closure wins over Resource additional availability
Resource-wide and assignment-specific exceptions remain distinct
contextualized Resources do not silently regain legacy wildcard Location semantics
price never changes silently during book
historical committed commercial facts are not reconstructed solely from mutable configuration
contextual CapacityClaims retain assignment provenance
shared-capacity locking remains additive
OfferingVersion remains append-only
Offering.active is the mutable parent kill-switch
contextual hold/reschedule never silently degrade to V3
semantic commands remain the configuration path; no generic CRUD shortcut
F2/F3/F4/F5/F6 scope does not leak into F1
```

---

## 11. Completion rule

Phase H is complete. The **feature itself is not yet merge-ready** until P5 documentation convergence, P6 cleanup and P7 exact-head evidence are complete.

The final merge-readiness claim must distinguish:

```text
implemented
proven
accepted F1 scope
future/non-goal
cleanup still required
```

A green historical SHA is evidence for the code at that SHA; final merge readiness requires a fresh green run on the final cleaned head.