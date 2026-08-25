# F3 current-state disposition — Live Service Operations

Status: **implementation-complete/evidence inventory for `feature/live-service-operations`; final exact-head CI required for merge**.

This inventory is intentionally old → new. It records what F3 retained, adapted, activated and proved without rewriting V3/F1/F2 history.

| Prior/current surface | Disposition | Current F3 meaning |
|---|---|---|
| `Reservation.during` | KEEP | planned/historical commitment only |
| Reservation OfferingVersion/location/commercial provenance | KEEP | never rewritten to match actual service |
| CapacityClaim | KEEP | capacity ledger remains Booking-owned |
| `ServiceQueue` | KEEP | FIFO serialization root |
| `QueueEntry` | ADAPT | arrival/wait/call truth; mutable pre-service expected workload; execution fields are compatibility mirrors |
| `QueueEntry.admitted_at` | KEEP | FIFO authority |
| `QueueEntry.called_at` | KEEP | DB-authoritative call time |
| `QueueEntry.service_started_at` | ADAPT | compatibility mirror; ServiceSession is execution authority |
| `QueueEntry.completed_at` | ADAPT | compatibility mirror; ServiceSession is execution authority |
| Queue statuses | KEEP + COMPOSE | waiting/called/no-show Queue-owned; serving/completed mirrored from Delivery transaction |
| `queue.join` | KEEP | subject-facing entry path |
| `queue.call_next` | KEEP | FIFO SQL + ServiceQueue locking preserved |
| `queue.leave` | KEEP | subject-facing cancellation path |
| `queue.check_in` | ADD | operator reservation check-in / walk-in admission |
| `queue.classify_expected_workload` | ADD | operator assign/correct/clear expected workload while waiting/called; revision + idempotency + audit/outbox |
| `queue.mark_no_show` | ADD | called-only no-show with revision/idempotency/audit/outbox |
| `queue.staff_read` | ADD + HARDEN | operator live projection; only waiting/called/serving |
| `queue.staff_history_read` | ADD | separate terminal-history projection; mandatory time window + bounded limit + stable cursor |
| customer queue status | KEEP + HARDEN | own authorized entry only; no other identity/workload leakage |
| `delivery.ReservationAccess` | KEEP | existing access lifecycle remains Delivery-owned |
| historical `delivery = deferred` statement | SUPERSEDED | Delivery active for ReservationAccess + F3 execution |
| `ServiceSession` | ADD | actual execution authority |
| `service_session.read` | ADD + HARDEN | factual snapshot with durable session/interruption facts and DB-observed durations; no forecast |
| `ServiceSessionInterruption` | ADD | durable pause/resume interval history |
| `ResourceActivity` | ADD | non-patient Resource occupation |
| `resource_activity.read` | ADD | operator tenant-filtered reconstruction of active or historical Resource occupation |
| F2 `ServiceClassification` | KEEP / DO NOT REUSE | discovery taxonomy remains distinct from live workload |
| `OperationalWorkloadClassification` | ADD + HARDEN | typed tenant vocabulary with stable key, revisioned rename, terminal deactivation and no physical delete |
| `workload.list` | ADD | active workload options for operator use |
| `workload.create` | ADD | create tenant workload vocabulary through product surface |
| `workload.update` | ADD | rename active workload with expected revision; key remains stable |
| `workload.deactivate` | ADD | preserve historical references while removing option from active list |
| arbitrary workload JSONB | REJECTED | no untyped workload vocabulary |
| frontend elapsed-service timer as authority | REJECTED | DB timestamps are authority; read-time durations are derived observations |
| QueueEntry F3 implicit times | ADAPT | a single DB initializer reads `clock_timestamp()` once when arrival/admission are omitted |
| normal authenticated business API | ADAPT | exact operator F3 capabilities composed into runtime |
| `0001_initial` | HISTORICAL | untouched |
| `migrations/sql/v3_candidate/*` | HISTORICAL | untouched |
| `0004_f2_discovery` | KEEP | direct parent of consolidated F3 `0005_live_service_ops` |
| provisional post-0005 F3 migrations | CONSOLIDATED | all behavior folded into `0005`; no post-0005 F3 revision remains |
| F4/F5 predictive/recovery concepts | OUT OF SCOPE | may consume F3 facts later |

## Implemented acceptance / race / proof matrix

| Risk | Evidence | Proven outcome |
|---|---|---|
| end-to-end F3 acceptance boundary | `tests/e2e/test_f3_acceptance_journey.py` | real Reservation traverses CheckIn → waiting → FIFO/CallNext → StartService → pause/resume → actual workload != expected → Complete; planning/capacity remain unchanged |
| live queue accidentally becomes history | `tests/e2e/test_f3_staff_queue_history.py` | live returns active states only; terminal history is separately authorized, time-bounded and cursor-paginated |
| workload vocabulary cannot be tenant-defined through product | `tests/e2e/test_f3_workload_management.py` | create/update/deactivate/list, revision, idempotent replay and audit/outbox are exercised through HTTP |
| workload tenant opacity | `tests/e2e/test_f3_workload_tenant_opacity.py` | foreign workload ID is as unusable as unknown ID and cannot be mutated |
| workload historical integrity | `tests/db/test_f3_workload_lifecycle.py` | key cannot be retargeted, revision advances exactly one step, inactive row is immutable and DELETE is rejected |
| ServiceSession without matching Queue lifecycle | `tests/db/test_f3_live_ops_invariants.py` | deferred constraint rejects incoherent commit |
| called-time / service-time ordering | `tests/db/test_f3_live_ops_invariants.py` | ServiceSession cannot predate call; DB ordering enforced |
| StartService same Resource | `tests/db/test_f3_live_resource_race.py` | one clean winner; losing QueueEntry remains called |
| ServiceSession vs ResourceActivity | `tests/db/test_f3_resource_activity_race.py` | one occupation wins; loser rolls back cleanly |
| StartService vs MarkNoShow | `tests/db/test_f3_start_no_show_race.py` | exactly one coherent lifecycle wins |
| pause vs pause | `tests/db/test_f3_pause_race.py` | one open interruption; conflicting transition cannot create parallel pause history |
| resume vs complete | `tests/db/test_f3_resume_complete_race.py` | paused session cannot silently complete; serialized valid state survives |
| ResourceActivity lifecycle | `tests/db/test_f3_resource_activity_lifecycle.py` | immutable identity/end semantics + revision discipline |
| interruption temporal order | `tests/db/test_f3_interruption_temporal.py` | interruption cannot predate/outlive execution |
| arrival/admission semantics | `tests/db/test_f3_arrival_admission_semantics.py` | omitted immediate arrival/admission share one exact DB transition instant |
| F3 RLS | `tests/db/test_f3_rls_isolation.py` | new tables preserve Organization boundary |
| F3 SQL authority | `tests/db/test_f3_live_ops_authority.py` | direct-write constraints defend assignment/lifecycle rules |
| stale StartService revision | `tests/e2e/test_f3_start_service_rejection.py` | 409 + no Session + Queue unchanged + no audit/outbox effect |
| StartService idempotency | `tests/e2e/test_f3_start_service_idempotency.py` | retry replay does not duplicate execution/effects |
| expected-workload lifecycle | `tests/e2e/test_f3_expected_workload_classification.py` | classify/reclassify/clear works before service; stale/terminal attempts do not rewrite truth |
| expected-workload adversarial authority | `tests/e2e/test_f3_expected_workload_adversarial.py` | conflicting key reuse rejected; foreign workload IDs remain opaque |
| operational reads / reconnect | `tests/e2e/test_f3_operational_reads.py` | factual Session/ResourceActivity state reconstructs from durable DB facts |
| check-in vs planning | `tests/e2e/test_f3_check_in_separation.py` | Reservation/claims unchanged; walk-in creates no Reservation |
| valid no-show | `tests/e2e/test_f3_no_show.py` | called entry becomes no_show, no Session, exactly one audit/outbox fact |
| customer privacy | `tests/e2e/test_live_queue_privacy.py` | foreign subject/staff execution data not exposed |
| tenant opacity | `tests/e2e/test_f3_tenant_opacity.py` | cross-tenant IDs do not become authority/discovery |
| capability/security matrix | `tests/e2e/test_f3_http_security_matrix.py` | exact F3 capabilities enforced at HTTP boundary |
| public surface contract | `tests/e2e/test_public_surface_contract.py` | F3 composition remains explicit in current OpenAPI/surface metadata |

## Current transaction protocols

### CheckIn / WalkIn

```text
lock active ServiceQueue
-> validate active subject + optional Reservation/Offering/workload
-> DB arrival/admission time
-> create QueueEntry
-> audit/outbox/idempotency
-> one commit
```

Reservation-backed check-in does not mutate Reservation/CapacityClaim. Walk-in persists `reservation_id = NULL`.

### CallNext

```text
lock ServiceQueue
-> select WAITING by (admitted_at,id)
-> FOR UPDATE SKIP LOCKED
-> mark exactly one CALLED with DB called_at
-> audit/outbox/idempotency
```

The acceptance journey observes this transition through the public endpoint rather than SQL-seeding `CALLED`.

### Workload vocabulary

```text
Create: idempotency -> insert stable key/display name -> audit/outbox
Update: idempotency -> lock row -> expected revision -> rename -> revision+1 -> audit/outbox
Deactivate: idempotency -> lock row -> expected revision -> active=false -> revision+1 -> audit/outbox
```

Database guards make `workload_key` immutable, reject physical deletion, require exact revision progression and make inactive rows terminal. Foreign IDs remain tenant-opaque.

### ClassifyExpectedWorkload

```text
idempotency
-> probe QueueEntry only to discover ServiceQueue
-> lock active ServiceQueue
-> lock QueueEntry
-> validate expected revision + WAITING/CALLED
-> validate optional active same-tenant workload classification
-> if materially changed: update expected workload + revision
-> audit/outbox
-> complete idempotency
-> one commit
```

### StartService

```text
idempotency
-> lock ServiceQueue
-> lock QueueEntry + expected revision + CALLED
-> lock Resource
-> validate ResourceLocationAssignment + occupation
-> DB start time
-> insert ServiceSession
-> QueueEntry SERVING + same compatibility start time
-> audit/outbox/idempotency
-> one commit
```

### Pause / Resume

Pause creates exactly one interruption and moves Session `active -> paused`; Resume closes that open interruption and moves `paused -> active`. QueueEntry remains `SERVING`.

### CompleteService

```text
lock Queue/Entry/Resource/Session
-> require active Session + serving QueueEntry
-> DB completion time
-> Session COMPLETED
-> QueueEntry COMPLETED + identical compatibility timestamp
-> audit/outbox/idempotency
-> one commit
```

### Staff live/history reads

`queue.staff_read` is deliberately active-only (`waiting`, `called`, `serving`). Terminal rows do not accumulate in the live result.

`queue.staff_history_read` is separate authority and requires a bounded time window. It paginates terminal states with a server-bounded limit and stable cursor. This is operational history, not F4 analytics.

### ServiceSession factual read

`service_session.read` reconstructs persisted execution plus interruption history and derives factual wall-clock/interruption/active-service seconds as observed by PostgreSQL. It is an observation snapshot, not ETA or remaining-work prediction.

### ResourceActivity

ResourceActivity and active/paused ServiceSession compete through the Resource row. Neither may coexist as an open live occupation on one Resource under F3 policy.

## Migration disposition

F3 is consolidated into:

```text
0004_f2_discovery
        ->
0005_live_service_ops
```

The final `0005` contains the QueueEntry single-clock initializer, ServiceSession/ResourceActivity hardening, and OperationalWorkloadClassification append-preserving/revision lifecycle guard directly. There is no post-0005 F3 revision in `migrations/versions`.

Repeated bootstrap and current-product CI must prove this consolidated graph from a fresh database. Historical `0001_initial` and frozen V3 candidate SQL remain untouched.

## Documentation precedence

Historical V3 baseline documents remain provenance. Current F3 ownership/surface changes are specified by:

```text
docs/v3/26-live-service-operations-contract.md
docs/v3/28-live-service-operations-integration-amendment.md
docs/10-module-ownership-map.md
src/request_engine/modules/queue/README.md
src/request_engine/modules/delivery/README.md
```

The implementation no longer treats Delivery/ServiceSession as deferred.
