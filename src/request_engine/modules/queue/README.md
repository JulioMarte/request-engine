# Queue module

> **Current status: active baseline + F3 live-operations extensions.**
>
> Queue owns waiting/admission/calling/no-show and released-slot recovery. Delivery owns actual
> ServiceSession execution. See `docs/v3/26-live-service-operations-contract.md` and
> `docs/v3/28-live-service-operations-integration-amendment.md`.

Queue owns two related but distinct operational capabilities:

1. `ServiceQueue` / `QueueEntry` — subjects waiting to be served now, FIFO among eligible entries.
2. `WaitlistEntry` / `SlotOpportunity` / `SlotOffer` — future capacity interest and deterministic
   recovery of released appointment slots.

## ServiceQueue

ServiceQueue serializes `CallNext` through the stable queue row and selects the earliest eligible
`waiting` entry by:

```text
(admitted_at, stable id)
```

Queue position is derived, never an authoritative mutable counter.

F3 keeps arrival and admission as separate facts:

```text
arrived_at
admitted_at
```

Current `queue.check_in` admits immediately, so both are written from the same PostgreSQL transaction
clock. The fields remain distinct so a future explicit arrival-before-admission policy does not need
to rewrite history.

### Current QueueEntry lifecycle

```text
WAITING --CallNext--> CALLED --service_session.start--> SERVING --service_session.complete--> COMPLETED
   |                    |
   +--cancel------------+--queue.mark_no_show--> NO_SHOW
```

Queue owns `WAITING`, `CALLED`, check-in/walk-in, no-show and FIFO selection. Delivery owns the actual
execution transitions that make a called entry `SERVING` and eventually `COMPLETED`.

`queue_entries.service_started_at` and `completed_at` are compatibility mirrors written atomically
with Delivery's ServiceSession. They are not independent execution authority.

`CALLED -> NO_SHOW` is allowed only while no ServiceSession exists. `SERVING -> NO_SHOW` is invalid.
Pause/resume does not change QueueEntry from `SERVING`.

### Check-in and walk-in

F3 adds staff/operator capability:

```text
queue.check_in
```

It is distinct from the existing subject-facing `queue.join`.

Reservation-backed check-in validates confirmed same-tenant planning context and creates QueueEntry
without mutating Reservation or CapacityClaim.

Walk-in creates QueueEntry with:

```text
reservation_id = NULL
```

No fake Reservation is created. Offering context may come from the Queue or an explicit same-tenant
Offering.

### Subject authority

Queue action capability and authority over a Party remain separate decisions.

- `JoinQueue` requires exact current Representation scope `queue.join` for the subject Party unless
  the authenticated actor has explicit `queue.subject_override`.
- `GetQueueStatus` and `LeaveQueue` require exact current Representation scope `queue.manage`, unless
  that same explicit operator override is present.
- `CallNext`, `queue.check_in`, `queue.mark_no_show` and `queue.staff_read` are operator capabilities;
  possessing a Party UUID never grants authority by itself.
- mutation-time Representation resolution uses the locking Party-authority primitive inside the
  authoritative PostgreSQL transaction where subject authority is required.

Queue consumes Tenancy authority vocabulary; it does not own Representation lifecycle.

### QueueEntry identity and optimistic concurrency

Caller-selected mutations target a concrete QueueEntry, not merely a Party currently found in a
queue. Existing mutable-row commands use expected revision where the contract requires stale-intent
detection.

`CallNext` deliberately does not accept expected revision because PostgreSQL selects the next FIFO
entry while holding the ServiceQueue serialization lock.

Current queue commands/queries include:

```text
queue.join
queue.leave
queue.status
queue.call_next
queue.check_in
queue.mark_no_show
queue.staff_read
```

Actual execution capabilities belong to Delivery:

```text
service_session.start
service_session.pause
service_session.resume
service_session.complete
service_session.read
```

## Customer vs staff reads

Customer queue status is subject-safe. It may expose the caller-authorized subject's status and safe
queue timestamps/derived entries-ahead, but never identities or operational details of other people.

Staff live queue uses a separate DTO/projection and may expose operational identity, expected workload
and actual execution context under `queue.staff_read`.

Do not reuse the staff projection as a customer DTO.

## Waitlist

A `WaitlistEntry` represents future interest and never consumes booking capacity.

`SlotOpportunity` is the stable coordination/serialization root for one released appointment
opportunity. It prevents duplicate release events and parallel candidate chains but does not prove
capacity availability; Booking remains authority.

`SlotOffer` is one expiring offer to one WaitlistEntry.

### Active SlotOffer uses a short CapacityHold

Before notifying a candidate, Queue coordinates with Booking to acquire a short Hold for the
opportunity. Only one active offered SlotOffer exists per SlotOpportunity.

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

Do not collapse ServiceQueue and Waitlist into one generic priority engine. No triage/scoring/auction
or optimization DSL exists in the current contract.

## Concurrency evidence

Critical Queue/Delivery races run against real PostgreSQL, including:

- concurrent `CallNext` selection;
- StartService vs StartService on one Resource;
- StartService vs ResourceActivity;
- StartService vs MarkNoShow;
- pause races;
- resume/complete races.

Tests must prove winner, loser and authoritative final state, not merely response codes.
