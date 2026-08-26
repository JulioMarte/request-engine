# Request Engine — F4 Live Capacity Projection Current-State Inventory

Status: **implementation planning / old-to-new disposition for `feature/live-capacity-projection`**.

Normative target: `29-live-capacity-projection-contract.md`.

This document records what F4 inherits, what it consumes, what it must add, and what it explicitly rejects/defer. It is not a claim that F4 is already implemented.

## 1. Starting point

`feature/live-capacity-projection` starts from the integrated F3 product baseline. F1 provides contextual supply/planning truth; F3 provides live Queue and Delivery facts.

The real migration lineage includes F3 historical-fact hardening after `0005_live_service_ops`; F4 migration work must use the actual repository head as predecessor.

## 2. Old -> new disposition

| Existing/new surface | Disposition | F4 treatment |
|---|---|---|
| `Reservation` | KEEP + CONSUME | Planning/provenance and same-day future workload; never rewritten by projection. |
| `CapacityClaim` | KEEP + CONSUME | Remains commitment/capacity authority. Projection never creates/releases claims. |
| Resource schedules/availability | KEEP + CONSUME | Booking/F1 continues to own effective availability composition. |
| Resource-at-Location assignment schedules | KEEP + CONSUME | Consumed through a published narrow planning contract. |
| Resource/assignment exceptions | KEEP + CONSUME | Must affect remaining effective operational intervals. |
| Location hours/exceptions | KEEP + CONSUME | Must affect projection horizon. |
| contextual Offering duration | KEEP + FALLBACK | May be a planned-duration fallback when F4 has no stronger workload estimate. |
| `ServiceQueue` | KEEP + CONSUME | Live queue scope remains Queue-owned. |
| `QueueEntry` | KEEP + CONSUME | Waiting/called truth, timestamps and expected workload. |
| FIFO admission ordering | KEEP + CONSUME | Projection may derive entries ahead; it does not persist position. |
| expected workload classification | KEEP + CONSUME | Pre-service estimate input; no predictive duration added to classification identity. |
| `ServiceSession` | KEEP + CONSUME | Current execution and completed history. |
| actual workload classification | KEEP + CONSUME | Historical execution evidence. |
| `ServiceSessionInterruption` | KEEP + CONSUME | Closed intervals excluded from active service; open intervals may make ETA indeterminate. |
| `ResourceActivity` | KEEP + CONSUME | Resource occupation is operational fact, not patient service. |
| F3 observational duration snapshot | KEEP + CONSUME | `active_service_seconds` is preferred historical productive-duration evidence. |
| `OperationalWorkloadClassification` | KEEP | Vocabulary only; do not add learned/predictive mutable duration semantics. |
| workload-estimate policy | ADD | Separate F4 configuration with provenance/revision semantics. |
| projection-scope policy | ADD | Explicit Queue + Resource + Location baseline mapping. |
| `live_capacity` bounded context | ADD | Owns projection semantics/configuration/read contracts. |
| persisted queue position | REJECT | Derived on read. |
| persisted ETA as authority | REJECT | Derived advisory state. |
| persisted remaining-capacity counter | REJECT | Derived advisory state. |
| automatic policy learning/mutation | REJECT | Observations may influence projection/recommendation, not silently mutate policy. |
| multi-resource queue optimizer | DEFER | Not hidden inside F4 ETA. |
| stop-intake automation | DEFER F5 | F4 only evaluates/advises. |
| delay communications | DEFER F5 | F4 produces facts/projections only. |
| recovery/rescheduling | DEFER F5 | Explicit later workflow. |

## 3. Source-module contract gaps

### Booking

Current Booking/F1 implementation owns the complex availability composition F4 needs. F4 must not import Booking adapters directly.

Required narrow published read capability, conceptually:

```text
ResourceOperationalAvailabilitySnapshot
  resource_id
  location_id
  observed_at
  remaining effective intervals
  same-day planning/commitment context as required
```

Exact contract shape is implementation-owned, but it must preserve Booking authority and avoid duplicating F1 composition logic.

### Queue

Current staff queue DTOs include identity/presentation fields that projection does not require. Publish/construct a narrower projection source, conceptually:

```text
QueueProjectionEntry
  queue_entry_id
  reservation_id?
  offering_id?
  status
  arrived_at
  admitted_at
  called_at?
  expected_workload_classification_id?
```

No customer identity is needed to calculate capacity.

### Delivery

F4 needs:

```text
current Resource execution/occupation snapshot
bounded completed ServiceSession history
active-service duration evidence
actual workload classification
```

Expose through a narrow Delivery contract/read surface rather than private adapter imports.

## 4. New F4 module

Target:

```text
src/request_engine/modules/live_capacity/
  contracts/
  application/
    queries/
    commands/      # configuration only
    ports/
  adapters/
    db/
  api/
  README.md
```

The exact private split remains flexible. HARD boundary: cross-module access goes through published contracts/read surfaces and no circular ownership is introduced.

## 5. Projection engine responsibilities

Prefer a pure deterministic domain/application core for:

```text
resolve_workload_estimate
calculate_remaining_current_service
build_remaining_workload
project_workload_over_intervals
estimate_queue_starts
calculate_projected_end
calculate_live_headroom
evaluate_intake
```

It should accept explicit facts and produce explicit results/provenance without SQLAlchemy/FastAPI/Pydantic dependence in the calculation core.

## 6. Database change disposition

Expected new migration: next revision after the actual current Alembic head, not after a stale documented predecessor.

Likely additions:

```text
live capacity projection policy/configuration
workload estimate policy/configuration
RLS / FORCE RLS
least-privilege grants
indexes supporting bounded historical reads
narrow read views/functions if they materially improve ownership/security
```

Do not add projection-state counters/tables in the initial implementation.

Potential historical query index shape should be validated against actual query plans, e.g. Resource + actual workload + completed-at for completed sessions.

## 7. Read consistency

Projection composition should run in one read-only coherent PostgreSQL snapshot with one DB-sourced `observed_at`.

Do not take Queue/Capacity mutation locks for advisory reads. Test that projection reads do not unnecessarily serialize normal CheckIn/CallNext/Start/Complete/Booking paths.

## 8. API/capability target

Likely staff surfaces:

```text
live_capacity.read
live_capacity.evaluate_intake
```

Likely customer-safe surface:

```text
live_capacity.customer_read
```

Final names must align with capability-registry conventions and existing HTTP operation naming.

Staff and customer response models remain separate contracts.

## 9. Deduplication matrix

| State | Remaining-work representation |
|---|---|
| same-day Reservation, no live QueueEntry | planned Reservation workload |
| Reservation + waiting/called QueueEntry | QueueEntry workload only |
| QueueEntry + active ServiceSession | ServiceSession remaining workload only |
| walk-in waiting/called | QueueEntry workload |
| completed service | zero |
| no-show | zero |

Tests must falsify each important boundary rather than merely snapshot the implementation.

## 10. Estimate provenance matrix

| Evidence | Preferred meaning |
|---|---|
| sufficient same Resource + actual workload history | strongest observed operational estimate |
| sufficient tenant workload history | observed fallback |
| configured workload policy | explicit policy fallback |
| applicable planned/contextual duration | planning fallback |
| none | unknown; no fabricated ETA |

Observed estimates do not mutate configured policy.

## 11. Uncertainty matrix

| Condition | Expected projection behavior |
|---|---|
| all required durations and intervals known | concrete projection |
| one future workload duration unknown | partial/unknown downstream projection |
| open ServiceSession interruption, unknown end | explicit indeterminate/blocking state |
| open ResourceActivity, unknown end | explicit indeterminate/blocking state |
| no remaining effective availability | known no-headroom result |
| invalid/missing projection configuration | semantic configuration failure |

Do not encode false certainty as zero duration or arbitrary average.

## 12. Required evidence ownership

### `tests/modules/live_capacity/`

Pure contract/domain projection behavior, estimator fallback, provenance, interval projection and DTO/application semantics.

### `tests/db/`

Cross-module PostgreSQL invariants, RLS/privileges, migration/backstop behavior, temporal snapshot and concurrency where database semantics are the guarantee.

### `tests/e2e/`

Production-like staff/customer journeys, deduplication, live mutation -> reprojection, privacy and no-authority-mutation proof.

### `tests/architecture/`

Module dependency/cross-contract boundaries and type separation where new surfaces require coverage.

## 13. Required regression/evidence scenarios

At minimum:

```text
scheduled capacity differs from live capacity without planning mutation
projection cannot create/release CapacityClaim
Reservation already checked in is counted once
active ServiceSession supersedes QueueEntry for remaining-work calculation
walk-in contributes without Reservation
future same-day Reservation contributes before check-in
completed/no-show work contributes zero
active-service elapsed time reduces remaining estimate
interruption seconds do not count as productive service
open interruption/activity yields explicit uncertainty
Location early close reduces horizon
additional-hours exception extends horizon
Resource/assignment exception creates discontinuous availability
history estimator is bounded/deterministic
insufficient history follows documented fallback
history never mutates configured policy
unknown duration never fabricates ETA
cross-tenant projection/history is opaque
customer projection exposes no other-customer/private operational data
one projection uses one DB observation snapshot
projection read does not take mutation/capacity locks
configuration race preserves revision semantics
fresh migration bootstrap succeeds
upgrade from actual predecessor head succeeds
```

## 14. Implementation sequence

```text
A. reconcile inherited documentation/migration truth
B. freeze F4 normative contract
C. complete this old->new inventory against code
D. register durable guarantees/evidence plan
E. introduce live_capacity module boundary
F. publish narrow Booking/Queue/Delivery source contracts
G. implement pure deterministic projection engine
H. implement projection/workload configuration policies
I. add F4 migration/RLS/indexes
J. add staff projection read
K. add read-only intake evaluation
L. add independently safe customer ETA read
M. add PostgreSQL/module/E2E/architecture evidence
N. update current-guarantees + current-proof-map
O. reconcile roadmap/README/ownership/migration docs
P. exact-head CI
```

## 15. Definition-of-Done gate

Do not call F4 complete merely because an endpoint returns queue position or ETA.

F4 closes only when the repository proves that it can derive explainable remaining-workload/time projections from authoritative current facts, preserve planning/live/execution separation, represent uncertainty explicitly, enforce privacy/tenant boundaries, and leave Booking/Queue/Delivery authority unchanged.
