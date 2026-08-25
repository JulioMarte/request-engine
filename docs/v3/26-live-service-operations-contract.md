# F3 — Live Service Operations contract

Status: **normative and implementation-complete on `feature/live-service-operations` / PR #79; final exact-head merge evidence required**.

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
- `queue` owns ServiceQueue, QueueEntry, FIFO admission/calling, expected-workload classification, no-show state, live staff queue reads, bounded queue history and operational workload vocabulary configuration.
- `delivery` keeps ReservationAccess and is activated for ServiceSession, ServiceSessionInterruption and ResourceActivity.
- operational workload vocabulary is tenant-scoped configuration consumed by Queue and Delivery. It is **not** F2 `ServiceClassification`; discovery taxonomy and live workload are intentionally independent concepts.

No new `live_operations` top-level module is introduced.

## 3. Queue semantics

FIFO queues remain ordered by:

```text
(admitted_at, id)
```

Position is derived. There is no mutable queue-position counter.

`arrived_at` and `admitted_at` are different semantics. F3 initially admits immediately, so normal check-ins/walk-ins record both from one PostgreSQL transition clock. For direct inserts that omit both values, a `BEFORE INSERT` initializer reads `clock_timestamp()` exactly once and assigns that same instant to both columns. The schema intentionally does **not** use two independent volatile timestamp defaults because PostgreSQL may evaluate them at different instants. If a future explicit arrival-before-admission flow supplies one timestamp while omitting the other, the initializer copies the supplied value rather than inventing a second instant. The fields remain separate so future explicit admission policy does not reinterpret history.

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

## 5. Workload classification and provisioning

F3 introduces a narrow typed tenant vocabulary:

```text
OperationalWorkloadClassification
  workload_key
  display_name
  active
  revision
```

It deliberately has no arbitrary JSON payload and no prediction/duration model.

The tenant can provision this vocabulary through explicit operator commands:

```text
workload.list
workload.create
workload.update
workload.deactivate
```

Lifecycle rules are deliberately narrow:

- `workload_key` is a stable, trimmed tenant-scoped identity and cannot be retargeted after creation;
- `display_name` may be renamed while the classification is active;
- update/deactivate require caller-observed `expected_revision`;
- all workload mutations require `Idempotency-Key`;
- deactivation preserves historical references; physical DELETE is rejected;
- an inactive classification is terminal/immutable;
- list returns active options for new operational use;
- foreign workload IDs are indistinguishable from unknown IDs at tenant-scoped mutation surfaces;
- material create/update/deactivate operations append audit and outbox facts.

Expected workload belongs to QueueEntry because it is an operational expectation before execution. It may be unknown at check-in and can be assigned, corrected or cleared later while the QueueEntry is still `waiting` or `called` through `queue.classify_expected_workload`.

That mutation:

- is operator-only;
- requires `Idempotency-Key`;
- requires the caller-observed QueueEntry `expected_revision`;
- locks ServiceQueue then QueueEntry;
- validates a non-null classification as active and same-tenant;
- advances QueueEntry revision only when the expected classification materially changes;
- appends audit/outbox only for a material classification change;
- rejects conflicting reuse of the same idempotency key with a different request fingerprint;
- keeps foreign-tenant workload identifiers opaque rather than granting authority through IDs;
- becomes invalid once service has started or the QueueEntry is otherwise terminal.

After `StartService`, expected workload is historical input and must not be rewritten to match actual execution.

Actual workload belongs to ServiceSession because it is an observation of execution.

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

`service_session.read` returns a factual observation snapshot rather than a prediction. In addition to the durable session facts it exposes an `observed_at` DB instant, interruption history and derived wall-clock, interruption and active-service seconds. For an open pause, elapsed interruption is measured only through that observation instant. These values answer “what has happened as of this read”; they do not estimate remaining service time, ETA or future capacity.

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

The interruption facts and `service_session.read` snapshot make wall-clock duration, interruption duration and active-service duration reconstructable without frontend timers.

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

`resource_activity.read` is an operator-only tenant-filtered reconstruction surface. It is queried by `resource_id`, defaults to active occupation only and may explicitly include ended history. A foreign or unknown Resource does not become a cross-tenant existence oracle. The read reports persisted occupation facts; it does not project future Resource availability.

Parallel/group service is a future explicit policy, not an accidental F3 behavior.

## 10. Authority

Exact runtime capabilities:

```text
queue.check_in                    operator
queue.classify_expected_workload  operator
queue.call_next                   operator
queue.mark_no_show                operator
queue.staff_read                  operator
queue.staff_history_read          operator

workload.list                     operator
workload.create                   operator
workload.update                   operator
workload.deactivate               operator

service_session.start             operator
service_session.pause             operator
service_session.resume            operator
service_session.complete          operator
service_session.read              operator

resource_activity.start           operator
resource_activity.end             operator
resource_activity.read            operator
```

Existing customer capabilities remain separate (`queue.join`, `queue.status`, `queue.leave`). Caller-supplied Organization IDs never create authority; actor Organization remains runtime scope.

All externally retryable F3 mutations require Idempotency-Key. Commands targeting an existing mutable row require `expected_revision` except server-selected `CallNext` and creation commands.

## 11. Staff vs customer reads

Customer queue status may expose only the caller-authorized subject's state, timestamps that belong to that subject, and derived `entries_ahead`. It never returns people ahead, names, other Party IDs, visit/workload information or staff-only execution facts.

The staff **live** queue is deliberately not an accidental history endpoint. Under `queue.staff_read`, it returns only operationally active QueueEntries:

```text
waiting
called
serving
```

Terminal states (`completed`, `no_show`, `cancelled`) are excluded from the live projection.

Terminal queue history is a separate operator surface under `queue.staff_history_read`. It requires a bounded time window, applies a server-bounded `limit`, and uses a stable cursor for pagination. This keeps “show me the queue now” semantically and operationally distinct from “inspect what happened earlier” without introducing F4/F5 analytics.

The staff DTO/projection may expose the identity required to operate the queue, scheduled context, expected workload, actual Resource/Location and ServiceSession state. Historical paging remains tenant-scoped and does not weaken customer privacy.

`service_session.read` and `resource_activity.read` are staff/operator surfaces. They are designed for factual reconstruction after refresh, reconnect or process restart; they are not customer queue projections.

Staff DTOs and customer DTOs remain distinct types.

## 12. Time and restart semantics

All live transition times use PostgreSQL `clock_timestamp()` inside authoritative transactions. Omitted QueueEntry arrival/admission times are initialized from one shared `clock_timestamp()` read, not from two independently evaluated volatile defaults. Browser/mobile timers are presentation only.

Refresh, reconnect, process restart and idempotent retry cannot erase or regenerate arrival, call, service, interruption or ResourceActivity timestamps. Read-time duration fields are explicitly observations derived from durable facts at the read's DB observation instant.

## 13. Events and audit

Material mutations append audit. Durable events are emitted for:

```text
queue.entry_checked_in.v1
queue.entry_called.v1                      # existing
queue.entry_expected_workload_classified.v1
queue.entry_no_show.v1
service_session.started.v1
service_session.paused.v1
service_session.resumed.v1
service_session.completed.v1
resource_activity.started.v1
resource_activity.ended.v1
workload.classification_created.v1
workload.classification_updated.v1
workload.classification_deactivated.v1
```

Events report committed operational facts; they do not mutate Reservation/capacity truth downstream.

## 14. Clinical-data exclusion

F3 may know operational workload classification, subject served, actual resource/location and durations. It must not store diagnosis, clinical notes, medication, medical history, symptoms or reason-for-visit free text.

No F3 body/table adds a general notes JSON/text field.

## 15. Migration semantics

F3 is the single Alembic revision `0005_live_service_ops` over `0004_f2_discovery`.

Existing QueueEntries are backfilled with `arrived_at = admitted_at`. The final F3 revision owns the single-clock QueueEntry initializer and the append-preserving/revisioned OperationalWorkloadClassification lifecycle guard directly; provisional follow-up F3 migrations used during invariant discovery are not part of the final graph. No historical ServiceSession is fabricated from legacy service timestamps: doing so would assert provenance that F3 cannot prove. Legacy timestamp rows remain historical compatibility facts; new F3 execution truth begins with actual ServiceSession creation.

Historical `0001_initial` and `migrations/sql/v3_candidate/*` are not rewritten.

## 16. Durable invariants

- Reservation planning, Queue waiting state and Service execution remain independent/reconstructable.
- the acceptance boundary proves a real Reservation can traverse CheckIn → FIFO/CallNext → StartService → interruption → Resume → Complete without SQL-seeding an intermediate called state;
- exactly zero or one ServiceSession exists per QueueEntry;
- QueueEntry/ServiceSession start and completion are transactionally coherent;
- actual operational timestamps are durable, DB-authoritative and monotonic;
- implicit immediate arrival/admission uses one DB transition instant rather than two independently evaluated volatile defaults;
- expected workload may evolve only before service starts; actual workload remains independently reconstructable on ServiceSession;
- workload vocabulary keys are stable, updates are revisioned, deactivation preserves history and deletion is forbidden;
- factual ServiceSession duration/interruption state can be reconstructed after reconnect without a frontend timer becoming authority;
- open/historical ResourceActivity can be reconstructed under the same tenant boundary as its mutations;
- customer queue projections never reveal another subject's identity/private context;
- the staff live queue contains only active operational states, while terminal history is separately authorized and bounded;
- Resource live service/activity conflicts follow the conservative F3 serialization policy;
- all tenant-owned F3 relations use same-Organization FKs and FORCE RLS.

## 17. Explicit non-goals

F3 does not implement ETA prediction, remaining-workload prediction, projected end-of-day, stop-intake automation, shortage prediction, delay messaging, automatic rescheduling, historical ML duration models, recommendations, EHR/clinical records, medical triage, general staff scheduling, or F4/F5 recovery policy.

F3's job is to produce trustworthy operational facts on which later projection/recovery features can safely depend.
