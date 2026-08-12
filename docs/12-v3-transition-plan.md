# Request Engine — V3 transition and reduction plan

> **Estado:** plan de migración arquitectónica pre-baseline.
>
> Este documento define cómo pasar del diseño V2.10 al capability-first V3 sin perder las garantías útiles ya diseñadas. No autoriza un `0001_initial` hasta completar los gates indicados aquí y en `11-capability-first-v3.md`.

---

## 1. Strategy

La migración es **subtractive first**.

No reconstruir todo desde cero y no seguir extendiendo el design chain V2 como si todas sus abstracciones fueran requisitos confirmados.

Orden:

```text
product semantics
→ capability contracts
→ module ownership
→ aggregate/transaction map
→ reduced invariant matrix
→ PostgreSQL redesign
→ vertical slices
→ race/reliability tests
→ initial baseline
```

El design chain SQL actual se conserva como executable design notebook hasta que el nuevo modelo esté suficientemente probado para sustituirlo.

---

## 2. Decision inventory

### Keep as foundational decisions

- modular monolith;
- PostgreSQL as local transactional/serialization authority;
- Python-owned command orchestration;
- no external I/O while authoritative DB transaction is open;
- module-first Python structure;
- explicit semantic commands instead of CRUD lifecycles;
- composite tenant integrity;
- idempotency records;
- outbox/event-after-commit pattern;
- append-oriented audit/history;
- canonical lock ordering;
- real PostgreSQL concurrency tests for race-sensitive behavior.

### Narrow or redefine

| V2 concept | V3 disposition |
|---|---|
| `Request` | Keep, narrow to durable new business demand |
| `RequestType` | Keep only business-demand types; mutation operations become Commands |
| `OfferingSelection` | Keep as needed for Request/intake scope; simplify before baseline |
| `OutcomeScope` | Remove from mandatory baseline |
| `Workflow` | Remove as universal domain noun/entity; use handlers/policies/scheduled actions/n8n |
| `CapacityAuthority` | Preserve serialization concept; simplify naming/storage if possible |
| `CapacityClaim` | Keep as common capacity consumption truth |
| `ResourceAllocation` | Re-evaluate; merge/remove if it duplicates reservation claim truth |
| `CapacityHold` | Keep for temporary local commitment; `active/consumed/released/expired` vocabulary preferred |
| `Reservation` | Keep |
| reschedule replacement Hold protocol | Replace with self-overlap-safe atomic claim replacement |
| `QueueEntry` | Keep but move to explicit ServiceQueue semantics |
| waitlist behavior inside delivery | Split into separate Waitlist/SlotOffer semantics |
| `ServiceSession` | Defer until a real execution vertical requires it |
| `Fulfillment` / corrections | Defer from baseline |
| `Payment*` advanced domain | Defer from baseline; retain design knowledge for later re-entry |
| `Dispatch` | Defer |
| `CapacityPool` | Defer |
| `PlanningRevision` | Defer with field-service planning |
| external capacity commitments | Defer |

### Add because product evidence now exists

- capability-oriented public surface;
- ServiceQueue separate from Waitlist;
- `SlotOffer` for deterministic released-capacity recovery;
- transactional communications;
- durable scheduled actions;
- attendance confirmation distinct from reservation confirmation;
- generic intake boundary;
- explicit n8n extension contract and promotion path;
- reminder plans for recurring non-reservation notifications.

---

## 3. Target module topology

### Baseline business modules

```text
modules/
├── tenancy/
├── catalog/
├── requests/
├── booking/
├── queue/
└── communications/
```

`requests` may own generic intake initially if the code remains small. Split an `intake` module only after independent policy/lifecycle justifies it.

`queue` owns both ServiceQueue and Waitlist because they share customer flow/capacity-opportunity language, but they remain different aggregates and policies. If they diverge substantially, split later.

### Deferred modules

Existing `payments`, `dispatch` and advanced `delivery` scaffolds should not be deleted blindly. During transition they are marked non-baseline/deferred. Once canonical V3 docs and SQL are stable, decide whether to archive their empty scaffolds or keep explicitly incubating modules.

### Platform

Add scheduling infrastructure under platform because leasing, clocks, retry and worker claiming are technical mechanics:

```text
platform/scheduling
```

The reason a reminder or expiry exists remains business-owned by booking/queue/communications/requests.

---

## 4. Request semantics migration

Current V2 examples such as:

```text
reschedule_reservation
cancel_reservation
```

must stop being default `RequestType` values.

Target distinction:

```text
RequestType:
  request_quote
  request_callback
  request_service
  submit_intake

Commands:
  CancelReservation
  RescheduleReservation
  ConfirmAttendance
  JoinQueue
  LeaveQueue
  AcceptSlotOffer
```

If a tenant later needs approval for cancellation/reschedule, that approval process can create a Request explicitly without redefining the base command semantics.

### Request lifecycle target

Prefer minimal lifecycle:

```text
open
completed
cancelled
failed
```

Do not use generic `waiting` to encode every blocker. Waiting on external work should be represented by durable facts/tasks/deadlines while the Request remains open unless the product requires a user-visible substate.

---

## 5. Booking/capacity reduction

### 5.1 Baseline model

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityClaim
CapacityHold
Reservation
```

Optional supporting rows may exist for relational integrity, but should not automatically become public domain nouns.

### 5.2 Capacity models

Only:

```text
exclusive
units
```

for the first baseline.

### 5.3 Claim truth

Investigate replacing the V2 `ResourceAllocation` + one-to-one `CapacityClaim` pair with one authoritative claim record that can represent:

```text
kind = hold | reservation
capacity source
interval
quantity
hold_id OR reservation_id
optional concrete Resource
status/release lineage
```

If operational assignment must later differ from capacity consumption, introduce a separate `ResourceAssignment` then; do not preserve duplicate state preemptively.

### 5.4 Reschedule transaction

Required proof:

```text
READ desired change
PLAN affected old/new capacity sources
LOCK Reservation
LOCK old/new sources in canonical order
VALIDATE final state excluding claims replaced by this operation
WRITE replacement claims + reservation revision atomically
EMIT event/outbox
COMMIT
```

The original reservation remains valid on rollback.

Required race cases include:

- same-resource overlapping self-reschedule;
- concurrent third-party booking into newly requested interval;
- concurrent cancellation vs reschedule;
- concurrent duplicate reschedule with same idempotency key;
- schedule exception created concurrently;
- unit-capacity self-replacement without temporary double counting.

---

## 6. Queue and waitlist model

### 6.1 ServiceQueue

Aggregate/serialization root candidate:

```text
ServiceQueue
```

`QueueEntry` contains:

```text
Party/subject
Offering/service scope when needed
admitted_at
status
called_at?
service_started_at?
completed_at?
```

Initial dequeue selection is FIFO among eligible waiting entries.

Critical races:

- two workers call next simultaneously;
- duplicate join;
- leave while being called;
- no-show transition vs service start.

### 6.2 Waitlist

`WaitlistEntry` expresses future acceptable capacity constraints.

It never consumes capacity by itself.

### 6.3 SlotOffer

A `SlotOffer` temporarily gives one candidate the opportunity to claim released capacity, but capacity correctness still belongs to booking.

Design options to test:

1. `SlotOffer` does not hold capacity; accept races normally with other booking traffic.
2. `SlotOffer` owns a short `CapacityHold` while offered.

Default recommendation: use a short Hold when exclusivity during the offer window is business-required; otherwise avoid artificial holds and simply revalidate on accept. The policy must be explicit per use case.

Critical races:

- offer expires exactly as accept occurs;
- two candidates accidentally offered same capacity;
- normal user books slot before standby accept;
- cancellation/release event delivered more than once;
- candidate becomes ineligible after offer creation.

---

## 7. Communications model

### 7.1 Business intent

`CommunicationTask` records an intended transactional communication after the originating business fact is committed.

Suggested shape:

```text
id
organization_id
purpose
audience/Party or endpoint reference
subject_type/subject_id or typed source reference
template_ref + version
render context snapshot/ref
channel policy
status
created_at
not_before?
expires_at?
dedupe_key
```

Avoid provider-specific fields in the task core.

### 7.2 Delivery attempts

`CommunicationDelivery` records each provider/channel attempt:

```text
communication_task_id
channel
provider
provider_message_id?
attempt_no
status
started_at
completed_at?
provider response/error classification
```

One task may produce multiple delivery attempts or fallback channels.

### 7.3 Contact endpoints and preferences

Keep endpoint truth minimal and tenant-scoped. Do not grow into CRM contact management.

Need explicit handling for:

- opt-out/preference;
- invalid endpoint;
- channel not supported;
- provider rate limit;
- duplicate callback;
- delivery status update.

Compliance rules are channel/jurisdiction-specific adapters/policies and must not be guessed generically.

---

## 8. Durable scheduling model

`ScheduledAction` is technical durable work, not business workflow.

Suggested lifecycle:

```text
pending
leased
completed
cancelled
dead
```

Fields/protocol:

```text
execute_at
lease_until
claim_token/fencing token
attempt_count
max_attempts
next_attempt_at
last_error_class
idempotency/dedupe identity
owner module + action type
payload/reference
```

Worker requirements:

- claim batches with non-blocking row locking;
- fence stale workers;
- bounded retries;
- exponential/provider-aware backoff where appropriate;
- dead-letter terminal state;
- manual replay command;
- observable scheduling lag;
- no external I/O inside claim transaction.

A business module can cancel/reschedule future actions by semantic reference when its authoritative state changes.

---

## 9. Appointment communication policy

Booking should emit authoritative facts such as:

```text
reservation.created
reservation.rescheduled
reservation.cancelled
attendance.accepted
attendance.declined
```

A versioned communication policy decides which tasks/actions are needed.

Example policy, not universal rule:

```text
on reservation created:
  confirmation now
  reminder T-48h
  attendance request T-24h

on attendance pending at T-12h:
  second reminder or voice fallback

on declined:
  cancel/release only if booking policy authorizes that consequence
```

Absence of response is not cancellation unless an explicit booking policy says so.

---

## 10. Reminder plans

`ReminderPlan` is business-owned recurring intent for reminders not derived from Reservation.

Initial use case: medication reminders configured by an authorized actor/system.

Important boundary:

Request Engine stores/executes the authorized reminder schedule and acknowledgement semantics. It does not infer medication instructions, dosage changes or clinical decisions.

Required semantics:

- timezone explicit;
- recurrence versioned;
- start/end/cancel;
- dedupe generation;
- missed execution behavior explicit (`skip`, `send_late_within_window`, etc.);
- acknowledgement optional;
- policy for escalation explicit and bounded.

---

## 11. n8n integration contract

### Outbound

Use outbox-delivered events/webhooks containing:

```text
event_id
event_type
organization_id
occurred_at
schema_version
correlation/request id where relevant
public subject references
minimal safe payload
```

### Callback

n8n must call semantic Request Engine commands, not update DB state directly.

Callbacks require:

- authenticated integration Principal;
- tenant binding;
- idempotency key;
- typed command schema;
- correlation to Request/provider event;
- current-state revalidation.

Example:

```text
quote.requested → n8n
n8n performs integrations/human step
POST semantic CompleteQuoteRequest / RecordQuoteResult
```

Do not accept arbitrary `set_status` callbacks.

---

## 12. SQL migration approach

Do not append V3 as `09-postgresql-v3.sql` on top of every V2 abstraction indefinitely.

Instead:

### Phase A — inventory

Map every V2 table/function/view/trigger to:

```text
KEEP
SIMPLIFY
REPLACE
DEFER
DELETE_FROM_BASELINE
```

### Phase B — construct clean V3 candidate schema

Create a fresh pre-baseline V3 schema candidate from the accepted contracts. Reuse proven SQL patterns (tenant FKs, range exclusion/claim locking, idempotency, outbox fencing) rather than retaining obsolete tables solely for migration continuity that does not yet exist in production.

### Phase C — compare

Run both designs against the required invariant/race suite where useful to ensure guarantees were not lost accidentally.

### Phase D — baseline

Only after vertical/race validation, produce a single clean `0001_initial` Alembic baseline.

There is no production migration history to preserve yet; optimize for conceptual integrity and testability.

---

## 13. Invariant matrix reset

Do not mechanically carry I01–I76 forward.

Create a V3 matrix grouped by promises actually made:

1. tenant/authority;
2. Request/intake;
3. local booking/capacity;
4. ServiceQueue;
5. Waitlist/SlotOffer;
6. communications;
7. scheduled actions;
8. provider callbacks/idempotency;
9. outbox/audit.

An invariant only enters the baseline if:

- a real baseline concept requires it;
- enforcement owner is explicit (`DB`, `application`, `both`, `external/reconciled`);
- race behavior is defined where concurrent violation is possible;
- at least one test demonstrates critical invariants.

---

## 14. API transition

Do not design endpoints by table.

Initial public capability groups:

```text
/business
/catalog
/appointments
/queue
/waitlist
/requests
/communications (mostly internal/admin; not raw CRUD)
```

Agent/tool surface can be narrower than HTTP admin surface.

All mutation endpoints require semantic command contracts and idempotency where retries are plausible.

---

## 15. Implementation order

### Phase 1 — canonical architecture

- add V3 product contract;
- update docs precedence;
- update module ownership target;
- ADR capability-first architecture;
- ADR durable transactional communications/scheduling.

### Phase 2 — repository topology

- introduce `queue` and `communications` modules;
- introduce `platform/scheduling`;
- mark/remove empty deferred modules according to ownership decision;
- update architecture tests and AGENTS guidance.

### Phase 3 — minimum domain/application code

Implement without waiting for full schema universe:

1. catalog/business info query;
2. booking commands/queries;
3. queue commands;
4. scheduling/outbox worker primitive;
5. communications task/delivery;
6. generic Request + n8n adapter.

### Phase 4 — clean V3 PostgreSQL candidate

Implement only tables/invariants needed by those verticals.

### Phase 5 — adversarial proof

Run concurrency and failure injection tests before expanding domain breadth.

### Phase 6 — baseline

Freeze `0001_initial` only when V3 proof gates pass.

---

## 16. First mandatory test matrix

At minimum:

### Booking

- double booking same exclusive resource;
- unit oversell;
- overlapping self-reschedule;
- cancel vs reschedule;
- expired Hold vs confirm;
- duplicate idempotent booking;
- schedule mutation vs booking.

### Queue

- concurrent `CallNext` returns one entry only;
- duplicate join;
- leave/call race;
- no-show/start race.

### Waitlist

- duplicate capacity-release event;
- SlotOffer accept vs expiry;
- two accepts against one slot;
- standby accept vs normal booking.

### Scheduling

- two workers claim same action;
- worker dies after claim;
- stale worker attempts completion after lease stolen;
- retry reaches dead state;
- cancellation while pending/leased.

### Communications

- duplicate task derivation/event;
- provider timeout after provider may have accepted message;
- duplicate provider callback;
- fallback channel does not double-send after late success without explicit policy.

### n8n callback

- duplicate callback;
- callback after Request state changed;
- wrong tenant/correlation;
- revoked integration authority.

---

## 17. Definition of done for the transition

The V3 architectural transition is complete when:

- canonical docs no longer tell two incompatible product stories;
- code module topology reflects active V3 capabilities;
- deferred concepts cannot accidentally become dependencies of baseline modules;
- V2 SQL design chain is replaced by a reduced V3 candidate;
- booking, queue, communications/scheduling and generic Request integration each have executable vertical behavior;
- critical races are automated against PostgreSQL;
- CI executes the architecture + DB + critical concurrency gates;
- `0001_initial` represents only promises the product can actually defend.
