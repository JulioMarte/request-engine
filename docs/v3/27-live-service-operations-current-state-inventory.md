# F3 current-state disposition — Live Service Operations

Status: **integrated predecessor implementation/evidence inventory**.

This inventory is intentionally old → new. It records what F3 retained, adapted, activated and proved without rewriting V3/F1/F2 history. F4 may consume these facts but must not reinterpret their ownership.

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
| `ServiceSessionInterruption` | ADD + HARDEN | durable pause/resume interval history; integrated historical-fact guards preserve closed facts |
| `ResourceActivity` | ADD | non-patient Resource occupation |
| `resource_activity.read` | ADD | operator tenant-filtered reconstruction of active or historical Resource occupation |
| F2 `ServiceClassification` | KEEP / DO NOT REUSE | discovery taxonomy remains distinct from live workload |
| `OperationalWorkloadClassification` | ADD + HARDEN | typed tenant vocabulary with stable key, revisioned rename, terminal deactivation and no physical delete |
| `workload.list/create/update/deactivate` | ADD | tenant workload vocabulary product surface |
| arbitrary workload JSONB | REJECTED | no untyped workload vocabulary |
| frontend elapsed-service timer as authority | REJECTED | DB timestamps are authority; read-time durations are derived observations |
| QueueEntry F3 implicit times | ADAPT | a single DB initializer reads `clock_timestamp()` once when arrival/admission are omitted |
| normal authenticated business API | ADAPT | exact operator F3 capabilities composed into runtime |
| `0001_initial` | HISTORICAL | untouched |
| `migrations/sql/v3_candidate/*` | HISTORICAL | untouched |
| `0004_geospatial_cross_tenant_discovery` | KEEP | predecessor of F3 `0005` |
| `0005_live_service_operations` | ADD / INTEGRATED | primary F3 schema + live-operation invariants |
| `0006_f3_historical_fact_hardening` | ADD / INTEGRATED HARDENING | append-only F3 hardening protecting completed ServiceSession/interruption history; current migration head before F4 |
| F4/F5 predictive/recovery concepts | OUT OF SCOPE | F4 consumes F3 facts without rewriting them |

## Implemented acceptance / race / proof matrix

Representative F3 evidence includes:

- `tests/e2e/test_f3_acceptance_journey.py` — Reservation → CheckIn → FIFO/CallNext → StartService → pause/resume → actual workload != expected → Complete while planning/capacity remain unchanged;
- `tests/e2e/test_f3_staff_queue_history.py` — live active-only queue vs separately authorized bounded terminal history;
- `tests/e2e/test_f3_workload_management.py` and tenant-opacity evidence — workload lifecycle, revisions, idempotency and authority;
- `tests/db/test_f3_live_ops_invariants.py` — Queue/ServiceSession coherence and temporal constraints;
- race tests for Resource service, ResourceActivity, no-show, pause and resume/complete conflicts;
- temporal/arrival-admission/RLS/authority tests;
- E2E rejection/idempotency/privacy/security/public-surface evidence;
- historical-fact hardening evidence associated with integrated `0006` protects completed ServiceSession and interruption facts from unsupported rewrite/delete behavior.

The durable evidence inventory and current proof map remain the machine-readable authority for current guarantee-to-proof mapping; this document is explanatory provenance.

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

### Workload vocabulary

```text
Create: idempotency -> insert stable key/display name -> audit/outbox
Update: idempotency -> lock row -> expected revision -> rename -> revision+1 -> audit/outbox
Deactivate: idempotency -> lock row -> expected revision -> active=false -> revision+1 -> audit/outbox
```

Database guards make `workload_key` immutable, reject physical deletion, require exact revision progression and make inactive rows terminal.

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

`queue.staff_read` is active-only (`waiting`, `called`, `serving`). `queue.staff_history_read` is separate authority and requires a bounded time window with server-bounded limit and stable cursor.

### ServiceSession factual read

`service_session.read` reconstructs persisted execution plus interruption history and derives factual wall-clock/interruption/active-service seconds as observed by PostgreSQL. It is an observation snapshot, not ETA or remaining-work prediction.

### ResourceActivity

ResourceActivity and active/paused ServiceSession compete through the Resource row. Neither may coexist as an open live occupation on one Resource under F3 policy.

## Migration disposition

The integrated F3 production-facing line is:

```text
0004_geospatial_cross_tenant_discovery
        ->
0005_live_service_operations
        ->
0006_f3_historical_fact_hardening
```

`0005` introduces the F3 schema, QueueEntry single-clock initializer, ServiceSession/ResourceActivity behavior and OperationalWorkloadClassification lifecycle protections.

`0006` is a real integrated append-only successor. It hardens historical execution facts after adversarial review, including immutability/append-preservation for completed ServiceSession and ServiceSessionInterruption history. It is **not** a provisional migration that was consolidated away.

Therefore F4 migration work must use `0006_f3_historical_fact_hardening` as the actual predecessor head unless the repository is explicitly rebaselined before F4 SQL begins.

Historical `0001_initial` and frozen V3 candidate SQL remain untouched.

## Documentation precedence

Historical V3 baseline documents remain provenance. Current F3 ownership/surface changes are specified by:

```text
docs/v3/26-live-service-operations-contract.md
docs/v3/28-live-service-operations-integration-amendment.md
docs/10-module-ownership-map.md
src/request_engine/modules/queue/README.md
src/request_engine/modules/delivery/README.md
```

For F4 projection semantics, `29-live-capacity-projection-contract.md` supersedes only the new projection concerns; it does not rewrite F3 execution facts.
