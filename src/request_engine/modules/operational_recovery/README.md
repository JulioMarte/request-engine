# Operational Recovery

`operational_recovery` owns F5 recovery composition after authoritative operational reality changes.

It owns:

- immutable material-shortfall recovery proposals and their replayable provenance;
- deterministic affected-Reservation recovery composition;
- explicit one-Reservation recovery execution facts;
- stale-proposal, idempotency and crash/retry orchestration;
- lineage from a recovery execution to the Communications task it caused;
- the durable `RecoveryIncident`/`RecoveryAction` workflow with the closed action set
  (stop/reopen intake, extend-day saga, contextual reschedule, intra-Organization
  replacement, communicate impact);
- the scheduled F4 reassessment handler that opens/updates/resolves incidents, persists
  automatic proposals and evaluates escalation/communication policy under source-revision
  fencing;
- a bounded reconciliation sweep that repairs lost F5 wake-ups by re-inserting the
  missing reassessment ScheduledAction; it never evaluates F4 itself and never
  resurrects `dead` or `cancelled` actions (operator replay only);
- `operational_recovery_escalations`: append-only escalation/communication policy
  outcomes, one immutable fact per incident and source revision.

The scheduled reassessment handler is the single escalation-policy evaluation authority.
Action-driven reprojection (`reconcile_recovery_incident` after owner mutations) advances
incident truth but records no escalation outcome; the material source changes those
actions cause trigger a fresh scheduled reassessment, which records the outcome.

It does **not** own:

- Resource schedules, capacity or CapacityClaims — Booking owns them;
- Reservation mutation — Booking owns the guarded reschedule command;
- live-capacity calculation — Live Capacity owns the F4 projection/recovery source;
- CommunicationTask, outbox, worker or provider delivery — Communications owns them;
- delivering customer communication — policy evaluation only requests it; delivery stays
  with the explicit `COMMUNICATE_IMPACT` action unless a later policy grants a system actor;
- the ScheduledAction claim runtime — the platform worker runtime owns it;
- a generic long-lived workflow engine.

## Published dependency direction

This module consumes only published contracts from:

```text
booking
communications
live_capacity
```

Those modules must not import `operational_recovery`.

## Command boundary

Proposal creation is an idempotent operator command because it persists an immutable snapshot.
Execution is an idempotent operator command for exactly one affected Reservation.

Execution deliberately persists `prepared` before invoking Booking. Booking receives a stable
idempotency identity derived from the recovery execution. This makes a crash after Booking commit
resumable without repeating the Reservation mutation.

Before a new Booking mutation, Booking validates the proposal's source Resource/Location revisions,
exact source commitment set and temporal window while holding its authoritative locks. Contextual
source or target rescheduling fails closed until Booking has a contextual reschedule implementation
that preserves assignment and commercial provenance.

See `docs/v3/32-operational-recovery-communications-contract.md` for the normative contract.
