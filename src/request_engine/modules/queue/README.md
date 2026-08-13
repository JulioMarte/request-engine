# Queue module

> **V3 baseline module.**

Owns two related but distinct operational capabilities:

1. `ServiceQueue` / `QueueEntry` — subjects waiting to be served now, FIFO among eligible entries.
2. `WaitlistEntry` / `SlotOpportunity` / `SlotOffer` — future capacity interest and deterministic recovery of released appointment slots.

## ServiceQueue

Baseline serializes `CallNext` through the stable `ServiceQueue` row and chooses the earliest eligible `waiting` entry by:

```text
(admitted_at, stable id)
```

At most one active QueueEntry exists for the same `(ServiceQueue, subject)` in baseline. Queue position is derived, never an authoritative mutable counter.

### Subject authority

Queue action capability and authority over a Party are separate decisions.

- `JoinQueue` requires exact current Representation scope `queue.join` for the subject Party, unless the authenticated actor has explicit `queue.subject_override`.
- `GetQueueStatus` and `LeaveQueue` require exact current Representation scope `queue.manage`, unless that same explicit operator override is present.
- `CallNext` is an operator action over the FIFO queue and does not require a Representation for the Party selected by the queue itself.
- Possession of a same-tenant Party UUID is never authority.
- Mutation-time Representation resolution uses the locking Party-authority primitive inside the authoritative PostgreSQL transaction; a concurrent revoke/deactivation serializes after a command that already established authority.
- Read-only queue status uses the non-locking current-authority resolver.

Queue consumes only Tenancy's published authority vocabulary and database authority surfaces; it does not own Representation lifecycle.

### QueueEntry identity and optimistic concurrency

`LeaveQueue` targets a concrete caller-observed QueueEntry, not merely a Party currently found in the queue.

The mutation contract is:

```text
queue_id
+ queue_entry_id
+ expected_revision
```

The public request body does not supply `subject_party_id`. PostgreSQL locks the exact QueueEntry identified by `queue_entry_id`, verifies that it belongs to the selected ServiceQueue, derives the subject Party from that authoritative row, establishes `queue.manage` authority for that Party, compares `expected_revision`, and only then performs the state transition.

This prevents an ABA/re-entry error. If Entry A is observed and later leaves, a new Entry B for the same Party is a different aggregate even if both rows independently have revision 1. A stale command for A can never cancel B.

`CallNext` deliberately does not accept `expected_revision`: it is not a caller-selected QueueEntry mutation. PostgreSQL chooses the deterministic next FIFO entry under the ServiceQueue serialization lock.

Initial commands/queries:

```text
JoinQueue
LeaveQueue
CallNext
StartServing
CompleteQueueEntry
MarkNoShow
GetQueueStatus
```

## Waitlist

A `WaitlistEntry` never consumes booking capacity.

`SlotOpportunity` is the stable coordination/serialization root for one released appointment opportunity. It exists so duplicate release events and sequential candidate offers cannot create parallel offer chains. It still does **not** prove capacity availability; booking remains authority.

`SlotOffer` is one expiring offer to one WaitlistEntry.

### Baseline decision: active SlotOffer uses a short CapacityHold

Before notifying a candidate, queue coordinates with booking to acquire a short Hold for the opportunity. This prevents the advertised slot from being consumed by ordinary booking before the candidate responds.

Only one active `offered` SlotOffer exists per SlotOpportunity. Candidate selection is FIFO among entries eligible for that concrete opportunity.

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

Initial waitlist commands/queries:

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

Do not collapse ServiceQueue and Waitlist into one generic priority engine. No triage/scoring/auction/optimization DSL in baseline.

Critical race behavior is specified in `docs/v3/02-pre-sql-contract.md` and must run against real PostgreSQL.
