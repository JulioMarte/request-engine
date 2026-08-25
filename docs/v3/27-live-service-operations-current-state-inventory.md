# F3 current-state disposition — Live Service Operations

Status: **implemented/evidence inventory for `feature/live-service-operations`**.

This inventory is intentionally old → new. It records what F3 retained, adapted, activated and proved
without rewriting V3/F1/F2 history.

| Prior/current surface | Disposition | Current F3 meaning |
|---|---|---|
| `Reservation.during` | KEEP | planned/historical commitment only |
| Reservation OfferingVersion/location/commercial provenance | KEEP | never rewritten to match actual service |
| CapacityClaim | KEEP | capacity ledger remains Booking-owned |
| `ServiceQueue` | KEEP | FIFO serialization root |
| `QueueEntry` | ADAPT | waiting/calling truth; arrival + expected workload; execution fields are compatibility mirrors |
| `QueueEntry.admitted_at` | KEEP | FIFO authority |
| `QueueEntry.called_at` | KEEP | DB-authoritative call time |
| `QueueEntry.service_started_at` | ADAPT | compatibility mirror; ServiceSession is execution authority |
| `QueueEntry.completed_at` | ADAPT | compatibility mirror; ServiceSession is execution authority |
| Queue statuses | KEEP + COMPOSE | waiting/called/no-show Queue-owned; serving/completed mirrored from Delivery transaction |
| `queue.join` | KEEP | subject-facing entry path |
| `queue.call_next` | KEEP | FIFO SQL + ServiceQueue locking preserved |
| `queue.leave` | KEEP | subject-facing cancellation path |
| `queue.check_in` | ADD | operator reservation check-in / walk-in admission |
| `queue.mark_no_show` | ADD | called-only no-show with revision/idempotency/audit/outbox |
| `queue.staff_read` | ADD | separate operator projection |
| customer queue status | KEEP + HARDEN | own authorized entry only; no other identity/workload leakage |
| `delivery.ReservationAccess` | KEEP | existing access lifecycle remains Delivery-owned |
| historical `delivery = deferred` statement | SUPERSEDED | Delivery active for ReservationAccess + F3 execution |
| `ServiceSession` | ADD | actual execution authority |
| `ServiceSessionInterruption` | ADD | durable pause/resume interval history |
| `ResourceActivity` | ADD | non-patient Resource occupation |
| F2 `ServiceClassification` | KEEP / DO NOT REUSE | discovery taxonomy remains distinct from workload |
| operational workload vocabulary | ADD | typed tenant-scoped expected/actual classification |
| arbitrary workload JSONB | REJECTED | no untyped workload vocabulary |
| frontend elapsed-service timer as authority | REJECTED | DB timestamps are authority |
| normal authenticated business API | ADAPT | exact operator F3 capabilities composed into runtime |
| `0001_initial` | HISTORICAL | untouched |
| `migrations/sql/v3_candidate/*` | HISTORICAL | untouched |
| `0004_f2_discovery` | KEEP | direct parent of consolidated F3 `0005_live_service_ops` |
| provisional post-0005 F3 migrations | CONSOLIDATED | behavior folded into `0005`; one F3 Alembic head |
| F4/F5 predictive/recovery concepts | OUT OF SCOPE | may consume F3 facts later |

## Implemented race / proof matrix

| Risk | Evidence | Proven outcome |
|---|---|---|
| ServiceSession without matching Queue lifecycle | `tests/db/test_f3_live_ops_invariants.py` | deferred constraint rejects incoherent commit |
| called-time / service-time ordering | `tests/db/test_f3_live_ops_invariants.py` | ServiceSession cannot predate call; DB ordering enforced |
| StartService same Resource | `tests/db/test_f3_live_resource_race.py` | one clean winner; losing QueueEntry remains called |
| ServiceSession vs ResourceActivity | `tests/db/test_f3_resource_activity_race.py` | one occupation wins; loser rolls back cleanly |
| StartService vs MarkNoShow | `tests/db/test_f3_start_no_show_race.py` | exactly one coherent lifecycle wins |
| pause vs pause | `tests/db/test_f3_pause_race.py` | one open interruption; conflicting transition cannot create parallel pause history |
| resume vs complete | `tests/db/test_f3_resume_complete_race.py` | paused session cannot silently complete; serialized valid state survives |
| ResourceActivity lifecycle | `tests/db/test_f3_resource_activity_lifecycle.py` | immutable identity/end semantics + revision discipline |
| interruption temporal order | `tests/db/test_f3_interruption_temporal.py` | interruption cannot predate/outlive execution |
| arrival/admission semantics | `tests/db/test_f3_arrival_admission_semantics.py` | DB-authored ordered timestamps |
| F3 RLS | `tests/db/test_f3_rls_isolation.py` | new tables preserve Organization boundary |
| F3 SQL authority | `tests/db/test_f3_live_ops_authority.py` | direct-write constraints defend assignment/lifecycle rules |
| stale StartService revision | `tests/e2e/test_f3_start_service_rejection.py` | 409 + no Session + Queue unchanged + no audit/outbox effect |
| StartService idempotency | `tests/e2e/test_f3_start_service_idempotency.py` | retry replay does not duplicate execution/effects |
| full execution lifecycle | `tests/e2e/test_f3_service_lifecycle.py` | start/pause/resume/complete keeps Queue, Session and interruption coherent |
| check-in vs planning | `tests/e2e/test_f3_check_in_separation.py` | Reservation/claims unchanged; walk-in creates no Reservation |
| valid no-show | `tests/e2e/test_f3_no_show.py` | called entry becomes no_show, no Session, exactly one audit/outbox fact |
| customer privacy | `tests/e2e/test_live_queue_privacy.py` | foreign subject/staff execution data not exposed |
| tenant opacity | `tests/e2e/test_f3_tenant_opacity.py` | cross-tenant IDs do not become authority/discovery |
| capability/security matrix | `tests/e2e/test_f3_http_security_matrix.py` | exact F3 capabilities enforced at HTTP boundary |
| public surface contract | `tests/e2e/test_public_surface_contract.py` | F3 composition does not silently distort unrelated API surface |

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

Reservation-backed check-in does not mutate Reservation/CapacityClaim. Walk-in persists
`reservation_id = NULL`.

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

Pause creates exactly one interruption and moves Session `active -> paused`; Resume closes that open
interruption and moves `paused -> active`. QueueEntry remains `SERVING`.

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

### MarkNoShow

Only a `CALLED` QueueEntry with no ServiceSession may transition to `NO_SHOW`.

### ResourceActivity

ResourceActivity and active/paused ServiceSession compete through the Resource row. Neither may
coexist as an open live occupation on one Resource under F3 policy.

## Migration disposition

F3 is consolidated into:

```text
0004_f2_discovery
        ->
0005_live_service_ops
```

Temporary follow-up F3 revisions used while discovering invariants were folded back into `0005`
before merge. Repeated bootstrap and current-product CI prove the consolidated graph rather than a
chain of provisional feature migrations.

## Documentation precedence

Historical V3 baseline documents remain provenance. Current F3 ownership/surface changes are
specified by:

```text
docs/v3/26-live-service-operations-contract.md
docs/v3/28-live-service-operations-integration-amendment.md
docs/10-module-ownership-map.md
src/request_engine/modules/queue/README.md
src/request_engine/modules/delivery/README.md
```

The implementation no longer treats Delivery/ServiceSession as deferred.
