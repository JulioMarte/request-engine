# F3 current-state disposition — Live Service Operations

Status: implementation inventory for `feature/live-service-operations`.

This inventory is intentionally old → new. It prevents F3 from rebuilding capabilities already proven in Queue/Booking and identifies which legacy fields cease to be independent authority.

| Current surface | Disposition | F3 meaning |
|---|---|---|
| `Reservation.during` | KEEP | planned/historical commitment only |
| Reservation OfferingVersion/location/commercial provenance | KEEP | never rewritten to match actual service |
| CapacityClaim | KEEP | capacity ledger remains Booking-owned |
| `ServiceQueue` | KEEP | FIFO serialization root |
| `QueueEntry` | ADAPT | remains live waiting/calling state; adds arrival + expected workload |
| `QueueEntry.admitted_at` | KEEP | FIFO authority |
| `QueueEntry.called_at` | KEEP | DB-authoritative call time |
| `QueueEntry.service_started_at` | ADAPT | compatibility projection only; new execution authority is ServiceSession |
| `QueueEntry.completed_at` | ADAPT | compatibility projection only; new execution authority is ServiceSession |
| `QueueEntry.offering_id` | KEEP | expected/commercial context, not actual workload |
| Queue statuses `waiting/called/serving/completed/cancelled/no_show` | KEEP | lifecycle survives F3 |
| `queue.join` | KEEP + ADAPT | customer/self queue entry; records `arrived_at` with admission |
| `queue.call_next` | KEEP | FIFO SQL and ServiceQueue locking remain unchanged |
| `queue.leave` | KEEP | existing subject-facing cancellation path |
| `queue.check_in` | ADD | staff reservation check-in / walk-in admission |
| `queue.mark_no_show` | ADD | `CALLED -> NO_SHOW` with revision/idempotency/audit |
| `queue.staff_read` | ADD | separate operator projection; never reuse customer DTO |
| `service_queue_status_v1` | KEEP | compatibility view |
| `service_queue_status_v2` | ADD | F3 projection joining QueueEntry to ServiceSession |
| existing patient queue status | KEEP + HARDEN | own entry + count only; no other identity/workload leakage |
| `delivery.ReservationAccess` | KEEP | existing delivery-owned access lifecycle is not semantically changed by F3 |
| `delivery` module status `deferred` | REPLACE | module is active: ReservationAccess + F3 execution |
| `ServiceSession` | ADD | actual execution truth |
| `ServiceSessionInterruption` | ADD | durable pause/resume intervals |
| `ResourceActivity` | ADD | non-patient resource occupation |
| F2 `ServiceClassification` | KEEP / DO NOT REUSE | cross-tenant discovery taxonomy remains distinct |
| operational workload vocabulary | ADD | typed tenant-scoped expected/actual workload classification |
| arbitrary workload JSONB | REMOVE FROM DESIGN | no untyped vocabulary |
| frontend elapsed-service timers as authority | REMOVE FROM DESIGN | timestamps + intervals derive elapsed time |
| `operational_app` configuration control-plane | KEEP | F3 is not automatically placed there |
| normal authenticated business API | ADAPT | adds exact operator live-operation capabilities |
| `0001_initial` | HISTORICAL | do not rewrite |
| `migrations/sql/v3_candidate/*` | HISTORICAL | do not rewrite for F3 |
| Alembic head `0004_f2_discovery` | KEEP | parent of F3 `0005_live_service_ops` |
| F4/F5 prediction/recovery concepts | OUT OF SCOPE | consume F3 facts later |

## Race / proof matrix

| Risk | Required winner | Required loser / rejection | Final authoritative assertion |
|---|---|---|---|
| concurrent CallNext | one entry called per serialized turn | other transaction selects a different remaining entry / none | no entry called twice; FIFO preserved |
| concurrent StartService same QueueEntry | exactly one ServiceSession | duplicate/stale start rejected or idempotent replay | one session + QueueEntry `serving` |
| stale QueueEntry revision | no mutation | revision conflict | no ServiceSession, QueueEntry unchanged |
| duplicate idempotency key/same fingerprint | original result | replay | same ServiceSession ID, no duplicate audit/outbox effect |
| idempotency key/different fingerprint | original unaffected | conflict | no second effect |
| no-show vs start | one transition wins under queue lock | incompatible transition rejected | never `NO_SHOW` with ServiceSession |
| pause vs pause | one open interruption | stale/unique conflict | exactly one open interruption + paused session |
| resume vs complete | valid serialized transition | complete while paused rejected | interruption history explicit; no silent closure |
| service vs ResourceActivity same Resource | one occupation wins | other conflicts | never simultaneous live service/activity |
| tenant A vs tenant B IDs | tenant A own state only | foreign operation/read fails | no cross-tenant row/effect |
| expected vs actual workload | both persist | neither overwrites the other | reconstructable mismatch |
| DB/application crash after commit | committed facts remain | retry replays | timestamps/IDs unchanged |

## Implementation consequence

F3 will extend the existing Queue path instead of replacing it. The most important compatibility constraint is preservation of the current `CallNext` implementation:

```sql
ORDER BY admitted_at, id
LIMIT 1
FOR UPDATE
```

and the existing ServiceQueue row lock. F3 code must compose around that serialization protocol.
