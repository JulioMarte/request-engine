# F3 — Live Service Operations integration amendment

Status: **normative post-V3 amendment for F3**.

This document records the narrow places where `docs/v3/26-live-service-operations-contract.md`
changes the older V3 baseline documents. It exists so historical baseline design remains readable
without leaving the current architecture ambiguous.

Precedence for the clauses below is:

```text
28-live-service-operations-integration-amendment.md
        +
26-live-service-operations-contract.md
        >
01-capability-contracts.md / 02-pre-sql-contract.md baseline text
```

Everything in the baseline documents not explicitly amended here remains in force.

## 1. Service execution is no longer deferred

`docs/v3/02-pre-sql-contract.md` describes `ServiceSession/Fulfillment accounting` as outside the V3
baseline. F3 does **not** retroactively change what the V3 baseline proved. It does activate a narrow
current-product execution model after that baseline:

```text
ServiceSession
ServiceSessionInterruption
ResourceActivity
OperationalWorkloadClassification
```

This activation is limited to live operational execution. It does not activate universal
Fulfillment, OutcomeScope, clinical records, payments or a generic workflow engine.

## 2. Queue no longer owns execution lifecycle

The conceptual V3 Queue commands `queue.start_service` / `queue.complete` (and the ownership-map
names `StartServing` / `CompleteQueueEntry`) are superseded for the current product by Delivery-owned
execution commands:

```text
service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read
```

Queue owns:

```text
ServiceQueue
QueueEntry
check-in / walk-in admission
expected-workload classification before service
FIFO CallNext
called state
MarkNoShow
staff/customer queue projections
bounded terminal queue history
operational workload vocabulary configuration
```

Delivery owns actual execution after a called QueueEntry is selected. QueueEntry `serving` and
`completed` plus the legacy service timestamps are compatibility mirrors written atomically with the
ServiceSession transition; they are not a second execution authority.

## 3. Current Queue state machine amendment

The current live path is:

```text
WAITING --CallNext--> CALLED --service_session.start--> SERVING
   |                    |                                  |
   +--cancel------------+--queue.mark_no_show--> NO_SHOW   +--service_session.complete--> COMPLETED
```

`CALLED -> NO_SHOW` is valid only before a ServiceSession exists. `SERVING -> NO_SHOW` is invalid.
Pause/resume changes ServiceSession state and interruption facts while QueueEntry stays `SERVING`.

Expected workload is pre-service Queue context rather than booking truth. It may be assigned,
corrected or cleared while a QueueEntry is `waiting` or `called`; after execution starts it is
historical input and cannot be rewritten to match actual workload.

## 4. Check-in, walk-in and classification amendment

F3 adds operator capabilities `queue.check_in` and `queue.classify_expected_workload`, distinct from
subject-facing `queue.join`.

A Reservation-backed check-in references existing planning truth but does not mutate Reservation or
CapacityClaim. A walk-in creates a QueueEntry with `reservation_id = NULL`; no fake Reservation is
created to make the live queue fit booking semantics.

For F3, an **active ServiceQueue permits walk-ins** when the normal same-tenant subject/offering/queue
validation succeeds. There is no separate `allow_walk_ins` configuration flag in F3. If a later
product requirement needs queue-specific reservation-only policy, that is an explicit configuration
extension rather than an implied hidden policy in the current contract.

Expected workload may be supplied at check-in or determined later. The later classification command
requires Idempotency-Key + expected QueueEntry revision, validates a non-null classification against
the active same-tenant workload vocabulary, and is valid only before service begins.

## 5. Resource occupation amendment

F3 makes Resource a live execution serialization root as well as a booking capacity root. Current
policy permits at most one of these open occupations for a Resource:

```text
active/paused ServiceSession
open ResourceActivity
```

The two kinds conflict in both directions and serialize on the Resource row. Parallel/group live
service requires a future explicit policy change; it must not appear accidentally through missing
locking or constraints.

## 6. Current capability names

Operator-facing F3 capabilities are:

```text
queue.check_in
queue.classify_expected_workload
queue.call_next
queue.mark_no_show
queue.staff_read
queue.staff_history_read

service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read

resource_activity.start
resource_activity.end
resource_activity.read

workload.list
workload.create
workload.update
workload.deactivate
```

Existing subject-facing queue capabilities remain separate. Every externally retryable F3 mutation
uses `Idempotency-Key`; commands against existing mutable aggregates require expected revision except
server-selected `CallNext` and creation commands.

## 7. Transaction, time and historical-fact amendment

`service_session.start` and `service_session.complete` are cross-module compositions executed in one
local PostgreSQL transaction. Queue and Delivery commit together or neither commits. Material live
mutations append audit/outbox in that same transaction.

Arrival/admission/call/service/interruption/activity timestamps are PostgreSQL-authoritative. F3
transition paths and QueueEntry F3 defaults use `clock_timestamp()`; authoritative elapsed time is
not derived from browser/mobile timers.

`ServiceSessionInterruption` is append-preserving execution history. Its tenant/session identity,
kind, start time, start actor and creation fact cannot be rewritten. The only update to an open
interruption is the atomic open → ended transition that supplies both end time and end actor; after
that the row is immutable and physical deletion is rejected. A completed `ServiceSession` is also an
immutable historical execution fact.

## 8. Staff history window semantics

`queue.staff_history_read` is a bounded operational-history surface, not an analytics API. Its
`window_start`/`window_end` bounds apply to **`QueueEntry.admitted_at`** using a half-open interval:

```text
admitted_at >= window_start
AND admitted_at < window_end
```

Therefore an entry admitted before midnight and completed after midnight belongs to the admission
window in which it entered the queue. F4/F5 analytics may introduce completion-time reporting, but
must not silently reinterpret this F3 cursor/window contract.

## 9. Documentation interpretation

When an older document says Delivery is deferred, ServiceSession is future-only, or Queue owns
StartServing/CompleteQueueEntry, interpret that statement as historical V3-baseline scope unless the
document has been updated for F3. Current ownership is defined by this amendment,
`26-live-service-operations-contract.md`, `docs/10-module-ownership-map.md`, and the module READMEs.
