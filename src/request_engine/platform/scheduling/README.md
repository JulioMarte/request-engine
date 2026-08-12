# Scheduling platform capability

Provides generic durable scheduled-work mechanics shared by business modules.

Owns technical concerns such as:

```text
clock abstraction
ScheduledAction persistence contract
claim batching
lease/fencing
retry/dead-letter mechanics
manual replay plumbing
scheduling lag telemetry
```

It does **not** decide why a reminder, SlotOffer expiry, request deadline or other future action exists. Business modules create/cancel/reschedule actions through narrow scheduling contracts and retain ownership of policy and payload semantics.

Workers must claim due actions using a race-safe PostgreSQL protocol, perform external I/O outside the claim transaction, and fence stale workers before recording completion.

Required reliability properties include bounded retries, terminal dead-letter state, idempotent completion, observable lag and safe recovery after worker death.
