# Queue module

> **V3 baseline module.**

Owns two related but distinct operational capabilities:

1. `ServiceQueue` / `QueueEntry` — subjects waiting to be served now, initially FIFO among eligible entries.
2. `WaitlistEntry` / `SlotOffer` — subjects willing to consume future capacity when a suitable slot becomes available.

A WaitlistEntry never consumes booking capacity by itself. `AcceptSlotOffer` must coordinate through booking's public contract and revalidate authoritative capacity. A SlotOffer may use a short booking `CapacityHold` only when the explicit business policy requires temporary exclusivity.

Initial commands/queries include:

```text
JoinQueue
LeaveQueue
CallNext
StartServing
CompleteQueueEntry
MarkNoShow
GetQueueStatus
JoinWaitlist
LeaveWaitlist
AcceptSlotOffer
DeclineSlotOffer
ExpireSlotOffer
GetWaitlistStatus
```

Do not collapse ServiceQueue and Waitlist into one generic priority engine. Do not introduce triage/optimization rules until a concrete business policy requires them.

Critical concurrency behavior belongs to real PostgreSQL tests: concurrent `CallNext`, duplicate joins, leave/call races, offer accept/expiry races, and standby acceptance competing with ordinary booking traffic.
