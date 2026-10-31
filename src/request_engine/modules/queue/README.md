# Queue module

> **Current status: active baseline + F3 live-operations extensions.**
>
> Queue owns waiting/admission/calling/no-show, pre-service expected-workload classification,
> tenant workload vocabulary configuration, active staff queue reads, bounded terminal queue history
> and released-slot recovery. Delivery owns actual ServiceSession execution. See
> `docs/v3/26-live-service-operations-contract.md` and
> `docs/v3/28-live-service-operations-integration-amendment.md`.

Queue owns two related but distinct operational capabilities:

1. `ServiceQueue` / `QueueEntry` — subjects waiting to be served now, FIFO among eligible entries.
2. `WaitlistEntry` / `SlotOpportunity` / `SlotOffer` — future capacity interest and deterministic recovery of released appointment slots.

## ServiceQueue

ServiceQueue serializes `CallNext` through the stable queue row and selects the earliest eligible `waiting` entry by:

```text
(admitted_at, stable id)
```

Queue position is derived, never an authoritative mutable counter.

For tenant onboarding, `POST /v1/queues` (`queue.configure`,
`operations.manage_supply` authority) creates one ServiceQueue bound to a
same-tenant Location with an optional Offering link. Selection stays FIFO only
(`policy_key` is DB-constrained to `'fifo'`). Queue creation is configuration
only: it admits nobody. `read_queue_supply` (via `contracts/onboarding.py`)
backs the `walk_in_queue` readiness fact of `GET /v1/onboarding/readiness`.

Operator configuration inventory uses `queue.read_configuration`, a Query distinct
from public `queue.list` and creation Command `queue.configure`. It exposes:

- `GET /v1/queues/configuration` (`queue_service_queue_configuration_list`);
- `GET /v1/queues/configuration/{queue_id}` (`queue_service_queue_configuration_read`).

Both require an explicit `authority_party_id`, the actor's current tenant standing
capability and current exact `operations.manage_supply` Representation, resolved
inside the read transaction under Principal/Party serialization. The Party is an
authority anchor; it does not manufacture tenant identity. No new default grant
is implied by these routes. List includes inactive queues and uses UUID keyset
pagination (`limit` 1–100, optional UUID `cursor`, `next_cursor` null at observed
end). This is a live read, not a snapshot. Detail returns the current queue ID,
key, display label, Location/Offering links, FIFO policy, active state and queue
revision. Missing and foreign IDs have the same 404 response. Responses are
`no-store`; unknown filters and malformed/beyond-bound inputs fail with 422.
These read operations require neither idempotency key nor expected revision,
admit no subjects and do not expose QueueEntry identities. No tool projection is
needed: curated dashboard navigation invokes these same owner HTTP operations.

### Closing and reopening a ServiceQueue (2026-10-25)

`POST /v1/queues/{queue_id}:set-active` (`queue_service_queue_set_active`,
capability `queue.configure`, owner Queue, `Idempotency-Key` required) closes
(`active=false`) or reopens (`active=true`) one queue. Body:
`{authority_party_id, expected_revision, active}`; response:
`{queue_id, queue_key, display_name, location_id, offering_id, active, revision}`.

- Authority: exact `operations.manage_supply` Representation of
  `authority_party_id`, checked inside the transaction **before** idempotency, so
  a withdrawn authority cannot read an old receipt back.
- Lock: the `service_queues` row `FOR UPDATE` — the same first lock as join,
  check-in and call-next (queue -> intake control -> entries/reservation). A
  concurrent admission either commits first (and is counted) or waits and then
  receives `409 queue_inactive`.
- Closing is refused while the queue still has `waiting`, `called` or `serving`
  entries: `409 service_queue_has_active_entries` with
  `details {queue_id, waiting, called, serving}`. There is no automatic drain:
  those entries are people physically waiting or being served, and cancelling
  them silently would be false. Staff finish, mark no-show or cancel them first.
  Terminal entries (`completed`, `cancelled`, `no_show`) do not block.
- Reopening requires the queue's Location to be active
  (`409 queue_configuration_conflict` otherwise).
- `expected_revision` mismatch: `409 service_queue_revision_conflict`
  (`details {queue_id, expected_revision, current_revision}`); requesting the
  current state: `409 service_queue_state_unchanged` (refresh, nothing to do).
  Missing/foreign queue: `404 queue_not_found`. The revision steps exactly once.
- Closing is not intake control: `service_queue_intake_controls` is untouched
  (pausing intake keeps the queue listed and serving; closing removes it from the
  public `queue_list`, which shows active queues only). The operator read
  `queue_service_queue_configuration_read/list` keeps showing closed queues with
  `active` and `revision`.
- Emits audit plus the PII-free outbox fact `service_queue.deactivated.v1` /
  `service_queue.activated.v1` (aggregate `ServiceQueue`; payload `queue_id`,
  `location_id`, `active`, `revision`). The change feed (ADR 0020) does not route
  ServiceQueue facts — its `queue.` route is QueueEntry-only — so live screens
  re-read after their own command response or on the next refresh.

F3 keeps arrival and admission as separate facts:

```text
arrived_at
admitted_at
```

Current `queue.check_in` admits immediately, so both are written from the same PostgreSQL transaction clock. For a direct insert that omits both values, the schema uses one `BEFORE INSERT` initializer that reads `clock_timestamp()` once and assigns that same instant to both fields. F3 deliberately does not use two independent volatile timestamp defaults. If exactly one value is supplied, the omitted value inherits it.

### Current QueueEntry lifecycle

```text
WAITING --CallNext--> CALLED --service_session.start--> SERVING --service_session.complete--> COMPLETED
   |                    |
   +--cancel------------+--queue.mark_no_show--> NO_SHOW
```

Queue owns `WAITING`, `CALLED`, check-in/walk-in, no-show, expected-workload classification and FIFO selection. Delivery owns the actual execution transitions that make a called entry `SERVING` and eventually `COMPLETED`.

`queue_entries.service_started_at` and `completed_at` are compatibility mirrors written atomically with Delivery's ServiceSession. They are not independent execution authority.

`CALLED -> NO_SHOW` is allowed only while no ServiceSession exists. `SERVING -> NO_SHOW` is invalid. Pause/resume does not change QueueEntry from `SERVING`.

### Check-in, walk-in and expected workload

F3 adds operator capabilities:

```text
queue.check_in
queue.classify_expected_workload
```

They are distinct from the existing subject-facing `queue.join`.

Reservation-backed check-in validates confirmed same-tenant planning context and creates QueueEntry without mutating Reservation or CapacityClaim.

Served-visit guard (INV-SERVED-VISIT-001): `queue.check_in` and `queue.join` refuse a
Reservation that already has a `completed` QueueEntry in **any** queue with
`409 reservation_already_served`. Check-in reads the Reservation `FOR SHARE` after
the ServiceQueue and intake-control locks (lock order: queue -> intake control ->
reservation), so a concurrent Booking cancel/reschedule serializes with the
admission. An entry that ended `cancelled` or `no_show` is not a served visit and
does not block a new check-in. Concurrent active entries of one Reservation in
*different* queues remain allowed: the Day Board multi-queue ambiguity contract
(`active_queue_entry_count > 1`, `docs/v3/43-same-day-triage.md`) depends on it,
and a lineage/handoff contract does not exist yet. A second active entry in the
*same* queue is refused by the per-subject active-entry rule
(`queue_entries_one_active_subject_uq`, `409 already_in_queue`). There is no
PostgreSQL unique backstop on `reservation_id`: a partial unique index over
completed entries would forbid completing both stages of a legitimate
multi-queue visit, so the guard is the admission transaction itself.

Every admission and triage fact appends a versioned outbox event on the
`QueueEntry` aggregate in its own transaction, which is what lets the change feed
(ADR 0020) signal it: `queue.entry_joined.v1`, `queue.entry_checked_in.v1`,
`queue.entry_called.v1`, `queue.entry_skipped.v1`, `queue.entry_recall_held.v1`,
`queue.entry_recall_released.v1`, `queue.entry_no_show.v1`,
`queue.entry_cancelled.v1` and `queue.entry_expected_workload_classified.v1`.
Payloads carry identifiers, closed enum values and revisions only; the operator's
free-text recall-hold reason stays in the audit/hold record and never in the
outbox.

Walk-in creates QueueEntry with:

```text
reservation_id = NULL
```

No fake Reservation is created. Offering context may come from the Queue or an explicit same-tenant Offering.

Expected workload may be known at check-in, but it does not have to be. An operator may assign, correct or clear `expected_workload_classification_id` later while the QueueEntry remains `waiting` or `called`.

`queue.classify_expected_workload`:

- requires `Idempotency-Key` and `expected_revision`;
- locks ServiceQueue before QueueEntry;
- validates non-null workload IDs as active and same-tenant;
- advances revision and emits audit/outbox only when the classification materially changes;
- rejects conflicting reuse of one idempotency key with a different request fingerprint;
- does not let a foreign-tenant workload UUID become authority or a tenant-existence oracle;
- is rejected after service begins or the QueueEntry becomes terminal.

Expected workload is mutable pre-service operational context, not immutable booking truth. Once service starts it becomes historical input; actual workload is recorded on Delivery's ServiceSession and may legitimately differ.

### Operational workload vocabulary

The tenant-defined F3 vocabulary is provisioned through Queue's operator surfaces:

```text
workload.list
workload.create
workload.update
workload.deactivate
```

`workload_key` is stable after creation. `display_name` may be changed only while active. Update/deactivate require expected revision and all mutations are idempotent, audited and outboxed. Deactivation preserves historical references; physical deletion is rejected by PostgreSQL and inactive classifications are terminal. `workload.list` returns only active options for new operational use.

This vocabulary is intentionally separate from F2 discovery `ServiceClassification`.

### Subject authority

Queue action capability and authority over a Party remain separate decisions.

- `JoinQueue` requires exact current Representation scope `queue.join` for the subject Party unless the authenticated actor has explicit `queue.subject_override`.
- `GetQueueStatus` and `LeaveQueue` require exact current Representation scope `queue.manage`, unless that same explicit operator override is present.
- `CallNext`, `queue.check_in`, `queue.classify_expected_workload`, `queue.mark_no_show`, `queue.staff_read`, `queue.staff_history_read` and workload management are operator capabilities; possessing a Party or workload UUID never grants authority by itself.
- mutation-time Representation resolution uses the locking Party-authority primitive inside the authoritative PostgreSQL transaction where subject authority is required.

Queue consumes Tenancy authority vocabulary; it does not own Representation lifecycle.

### QueueEntry identity and optimistic concurrency

Caller-selected mutations target a concrete QueueEntry, not merely a Party currently found in a queue. Existing mutable-row commands use expected revision where the contract requires stale-intent detection.

`CallNext` deliberately does not accept expected revision because PostgreSQL selects the next FIFO entry while holding the ServiceQueue serialization lock.

Current Queue/F3 commands and queries include:

```text
queue.join
queue.leave
queue.status
queue.call_next
queue.check_in
queue.classify_expected_workload
queue.mark_no_show
queue.staff_read
queue.staff_history_read
workload.list
workload.create
workload.update
workload.deactivate
```

Actual execution capabilities belong to Delivery:

```text
service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read
resource_activity.start
resource_activity.end
resource_activity.read
```

## Customer vs staff reads

Customer queue status is subject-safe. It may expose the caller-authorized subject's status and safe queue timestamps/derived entries-ahead, but never identities or operational details of other people.

`queue.staff_read` is specifically the **live** operator projection. It returns only:

```text
waiting
called
serving
```

Terminal states do not accumulate in the live response.

The live staff projection also exposes Queue's canonical recall gate. `recall_eligible=false` means the entry is presently excluded from normal recall selection by an active Queue-owned hold or skip. When a hold is active, the projection may expose its condition, release target and operator reason; an unconsumed skip exposes its reason. These are projections of existing triage facts, not a second mutable readiness state.

Do not reinterpret recall eligibility as clinical readiness, medical triage severity, insurance authorization or a generic workflow stage. Those meanings belong to their owning authority or vertical. If a future workflow needs an external prerequisite, model the prerequisite at the correct boundary and map only the resulting operational gate into Queue; do not add healthcare-specific fields to QueueEntry.

`queue.staff_history_read` is a distinct operator capability and endpoint for terminal queue history. It requires a bounded time window, enforces a server-bounded page size and advances with a stable cursor. Terminal entries report `recall_eligible=false` and no active hold/skip because recall eligibility is no longer meaningful after terminalization. This keeps operational history bounded without turning F3 into an analytics subsystem.

Delivery's `service_session.read` and `resource_activity.read` reconstruct factual execution/occupation after refresh or reconnect; they are not customer Queue DTOs and do not provide F4 predictions.

Do not reuse staff projections as customer DTOs.

## Waitlist

A `WaitlistEntry` represents future interest and never consumes booking capacity.

`SlotOpportunity` is the stable coordination/serialization root for one released appointment opportunity. It prevents duplicate release events and parallel candidate chains but does not prove capacity availability; Booking remains authority.

`SlotOffer` is one expiring offer to one WaitlistEntry.

### Active SlotOffer uses a short CapacityHold

Before notifying a candidate, Queue coordinates with Booking to acquire a short Hold for the opportunity. Only one active offered SlotOffer exists per SlotOpportunity.

Candidate selection is FIFO among entries eligible for the concrete opportunity.

`AcceptSlotOffer` atomically coordinates:

```text
SlotOpportunity open
+ SlotOffer active/unexpired
+ CapacityHold active/unexpired
→ Reservation confirmed
+ SlotOffer accepted
+ SlotOpportunity filled
+ WaitlistEntry fulfilled
```

Decline/expiry releases the short Hold before the Opportunity advances to another candidate.

Waitlist commands/queries remain:

```text
JoinWaitlist
LeaveWaitlist
GetWaitlistStatus
CreateSlotOpportunity            # event-driven/internal
OfferNextWaitlistCandidate       # internal
AcceptSlotOffer
DeclineSlotOffer
ExpireSlotOffer                  # ScheduledAction target
```

Do not collapse ServiceQueue and Waitlist into one generic priority engine. No triage/scoring/auction or optimization DSL exists in the current contract.

## Acceptance and concurrency evidence

The F3 acceptance journey traverses a real Reservation through check-in, FIFO/CallNext, service start, interruption, resume and completion without SQL-seeding an intermediate called state. It also proves Reservation/CapacityClaim planning remains unchanged and expected workload may differ from actual workload.

Critical Queue/Delivery races run against real PostgreSQL, including:

- concurrent `CallNext` selection;
- StartService vs StartService on one Resource;
- StartService vs ResourceActivity;
- StartService vs MarkNoShow;
- pause races;
- resume/complete races.

Tests must prove winner, loser and authoritative final state, not merely response codes.
