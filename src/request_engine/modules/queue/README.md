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
