# F3 — Live Service Operations contract

Status: **normative for `feature/live-service-operations`**.

This contract activates actual service execution without collapsing planning, waiting and execution into one mutable record.

## 1. Product boundary

The three authoritative facts are deliberately different:

```text
Reservation
  planned commitment and historical booking context

QueueEntry
  real arrival/admission/calling state for a subject waiting now

ServiceSession
  actual execution: where/by whom service really started and ended
```

Normative rule:

> Booking records what was committed, Queue records who is waiting/called, and Delivery records what actually happened. No layer rewrites another layer to make history appear consistent.

A `ServiceSession` never changes `Reservation.during`, OfferingVersion, booking provenance or CapacityClaim ownership merely because actual execution differed from the plan.

## 2. Ownership

- `booking` continues to own Reservation and capacity.
- `queue` owns ServiceQueue, QueueEntry, FIFO admission/calling and no-show state.
- `delivery` keeps ReservationAccess and is activated for ServiceSession, ServiceSessionInterruption and ResourceActivity.
- operational workload vocabulary is tenant-scoped configuration consumed by Queue and Delivery. It is **not** F2 `ServiceClassification`; discovery taxonomy and live workload are intentionally independent concepts.

No new `live_operations` top-level module is introduced.

## 3. Queue semantics

FIFO queues remain ordered by:

```text
(admitted_at, id)
```

Position is derived. There is no mutable queue-position counter.

`arrived_at` and `admitted_at` are different semantics. F3 initially admits immediately, so new check-ins/walk-ins record both from the same PostgreSQL transaction clock. The schema keeps them separate so a future explicit arrival-before-admission feature does not need to reinterpret history.

State machine:

```text
WAITING --CallNext--> CALLED --StartService--> SERVING --CompleteService--> COMPLETED
   |                    |
   +--cancel------------+--MarkNoShow--> NO_SHOW
```

`SERVING -> NO_SHOW` is invalid. `CALLED -> NO_SHOW` is valid only while no ServiceSession exists.

## 4. Check-in and walk-ins

Staff `queue.check_in` is distinct from the existing subject-facing `queue.join` capability.

Reservation-backed check-in:

- Reservation must be in the same Organization and confirmed;
- Reservation subject must equal QueueEntry subject;
- if the ServiceQueue pins a Location, Reservation Location must match it;
- if the ServiceQueue pins an Offering, Reservation OfferingVersion must belong to that Offering;
- no Reservation planning fact is mutated.

Walk-in:

- `reservation_id IS NULL`;
- no fake Reservation is created;
- Offering context may come from the Queue or an explicit same-tenant Offering;
- the subject must be an active tenant Party.

Both forms produce one QueueEntry and DB-authoritative `arrived_at/admitted_at`.

## 5. Workload classification

F3 introduces a narrow typed tenant vocabulary:

```text
OperationalWorkloadClassification
  workload_key
  display_name
  active
```

It deliberately has no arbitrary JSON payload and no prediction/duration model.

Expected workload is captured on QueueEntry because it exists before execution. Actual workload is captured on ServiceSession because it is an observation of execution.

Therefore this is valid and reconstructable:

```text
expected = follow_up
actual   = extended_consultation
```

without changing the Reservation or OfferingVersion.

## 6. ServiceSession

Cardinality in F3:

```text
QueueEntry 1 -- 0..1 ServiceSession
```

A session has:

```text
organization_id
queue_entry_id
resource_id
location_id
actual_workload_classification_id?
status = active | paused | completed
started_at
completed_at?
revision
```

Actual Resource and Location are required in F3. Start must prove that the Resource has an active ResourceLocationAssignment covering the DB start instant at the chosen Location.

`started_at` and `completed_at` are PostgreSQL-authoritative timestamps. `scheduled_at` is not duplicated; scheduled time remains derivable from Reservation when one exists.

Legacy `queue_entries.service_started_at/completed_at` remain only as a compatibility projection for `service_queue_status_v1`. F3 commands write them atomically from the same DB timestamp as ServiceSession; Delivery is the authoritative execution source and new read models use ServiceSession.

## 7. Atomic Queue ↔ Delivery transitions

`service_session.start` is one transaction:

1. acquire idempotency;
2. lock ServiceQueue;
3. lock QueueEntry and validate expected revision + `CALLED`;
4. lock actual Resource;
5. validate active ResourceLocationAssignment and no conflicting activity/session;
6. create ServiceSession with DB time;
7. move QueueEntry to `SERVING` and compatibility timestamp;
8. append audit/outbox;
9. complete idempotency;
10. commit.

The committed states `SERVING + no ServiceSession` and `active ServiceSession + CALLED` are forbidden.

`service_session.complete` similarly completes ServiceSession and QueueEntry in one transaction. Completion while paused is rejected; a pause must be explicitly resumed first so interruption history is never silently closed.

Canonical live-operation lock order is:

```text
ServiceQueue -> QueueEntry -> Resource -> ServiceSession -> open interruption/activity
```

A command may perform an unlocked probe to discover IDs, but every authoritative fact is re-read after acquiring the canonical roots.

## 8. Interruptions

A ServiceSessionInterruption is a durable fact:

```text
kind = emergency | break | administrative | other_operational
started_at
ended_at?
started_by_principal_id
ended_by_principal_id?
```

F3 allows at most one open interruption per ServiceSession.

Pause atomically creates the interruption and changes session `active -> paused`. Resume atomically closes the exact open interruption and changes `paused -> active`.

QueueEntry remains `SERVING` while paused.

This supports independent derivation of wall-clock duration, interruption duration and active-service duration without frontend timers.

## 9. ResourceActivity

ResourceActivity records non-patient operational occupation:

```text
break | emergency | administrative | other_operational
```

It is not represented by a fake Party, QueueEntry, Reservation or ServiceSession.

F3 concurrency policy is intentionally conservative:

- at most one open ResourceActivity per Resource;
- at most one active/paused ServiceSession per Resource;
- an open ResourceActivity conflicts with starting a ServiceSession on that Resource;
- an active/paused ServiceSession conflicts with starting ResourceActivity.

Parallel/group service is a future explicit policy, not an accidental F3 behavior.

## 10. Authority

Exact runtime capabilities:

```text
queue.check_in              operator
queue.call_next             operator
queue.mark_no_show          operator
queue.staff_read            operator

service_session.start       operator
service_session.pause       operator
service_session.resume      operator
service_session.complete    operator
service_session.read        operator

resource_activity.start     operator
resource_activity.end       operator
```

Existing customer capabilities remain separate (`queue.join`, `queue.status`, `queue.leave`). Caller-supplied Organization IDs never create authority; actor Organization remains runtime scope.

All externally retryable F3 mutations require Idempotency-Key. Commands targeting an existing mutable row require `expected_revision` except server-selected `CallNext` and creation commands.

## 11. Staff vs customer reads

Customer queue status may expose only the caller-authorized subject's state, timestamps that belong to that subject, and derived `entries_ahead`. It never returns people ahead, names, other Party IDs, visit/workload information or staff-only execution facts.

Staff live queue view may return the identity required to operate the queue, scheduled context, expected workload, actual Resource/Location and ServiceSession state under `queue.staff_read`.

Staff DTOs and customer DTOs remain distinct types.

## 12. Time and restart semantics

All transition times use `clock_timestamp()` inside PostgreSQL transactions. Browser/mobile timers are presentation only.

Refresh, reconnect, process restart and idempotent retry cannot erase or regenerate arrival, call, service or interruption timestamps.

## 13. Events and audit

Material mutations append audit. Durable events are emitted for:

```text
queue.entry_checked_in.v1
queue.entry_called.v1              # existing
queue.entry_no_show.v1
service_session.started.v1
service_session.paused.v1
service_session.resumed.v1
service_session.completed.v1
resource_activity.started.v1
resource_activity.ended.v1
```

Events report committed operational facts; they do not mutate Reservation/capacity truth downstream.

## 14. Clinical-data exclusion

F3 may know operational workload classification, subject served, actual resource/location and durations. It must not store diagnosis, clinical notes, medication, medical history, symptoms or reason-for-visit free text.

No F3 body/table adds a general notes JSON/text field.

## 15. Migration semantics

F3 is Alembic revision `0005_live_service_ops` over `0004_f2_discovery`.

Existing QueueEntries are backfilled with `arrived_at = admitted_at`. No historical ServiceSession is fabricated from legacy service timestamps: doing so would assert provenance that F3 cannot prove. Legacy timestamp rows remain historical compatibility facts; new F3 execution truth begins with actual ServiceSession creation.

Historical `0001_initial` and `migrations/sql/v3_candidate/*` are not rewritten.

## 16. Durable invariants

- Reservation planning, Queue waiting state and Service execution remain independent/reconstructable.
- exactly zero or one ServiceSession exists per QueueEntry;
- QueueEntry/ServiceSession start and completion are transactionally coherent;
- actual operational timestamps are durable, DB-authoritative and monotonic;
- expected and actual workload classifications remain independently reconstructable;
- customer queue projections never reveal another subject's identity/private context;
- Resource live service/activity conflicts follow the conservative F3 serialization policy;
- all tenant-owned F3 relations use same-Organization FKs and FORCE RLS.

## 17. Explicit non-goals

F3 does not implement ETA prediction, remaining-workload prediction, projected end-of-day, stop-intake automation, shortage prediction, delay messaging, automatic rescheduling, historical ML duration models, recommendations, EHR/clinical records, medical triage, general staff scheduling, or F4/F5 recovery policy.

F3's job is to produce trustworthy operational facts on which later projection/recovery features can safely depend.
