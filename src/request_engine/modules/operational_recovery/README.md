# Operational Recovery

`operational_recovery` owns recovery composition after authoritative operational reality changes.

It owns:

- immutable material-shortfall recovery proposals and replayable provenance;
- deterministic affected-Reservation recovery composition;
- explicit one-Reservation recovery execution facts;
- stale-proposal, idempotency and crash/retry orchestration;
- lineage from a recovery execution to the Communications task it caused;
- the durable `RecoveryIncident` / `RecoveryAction` workflow with the closed action set: stop/reopen intake, extend-day, contextual reschedule, intra-Organization replacement and communicate impact;
- scheduled reassessment, escalation-policy evaluation and bounded reconciliation of lost wake-ups;
- operator-granted autonomous reschedule policy within its accepted envelope.

It does **not** own the underlying facts it coordinates:

- Resource schedules, assignment schedules, capacity, CapacityClaims and Reservation mutation -> `booking`;
- Location schedule truth -> `catalog`;
- ServiceQueue intake state -> `queue`;
- live-capacity calculation/checkpoints -> `live_capacity`;
- CommunicationTask/outbox/provider delivery -> `communications`;
- ScheduledAction claim/fencing runtime -> `platform`.

## Published dependency direction

Recovery is an orchestration owner, so its real synchronous dependency graph is explicit:

```text
operational_recovery -> booking.contracts
operational_recovery -> catalog.contracts
operational_recovery -> communications.contracts
operational_recovery -> live_capacity.contracts
operational_recovery -> queue.contracts
```

`catalog` and `queue` are not hidden behind `bootstrap`: extend-day invokes Catalog's published Location schedule contract and stop/reopen-intake invokes Queue's published intake-control contract. The adapters that translate Recovery's local workflow ports to those owner contracts live under `operational_recovery/adapters/` so architecture tooling can see the dependencies.

Those target modules must not import `operational_recovery`; the dependency graph remains one-way and acyclic.

## Command boundary

Proposal creation is an idempotent operator command because it persists an immutable snapshot. Execution is an idempotent operator command for exactly one affected Reservation.

Execution deliberately persists `prepared` before invoking Booking. Booking receives a stable idempotency identity derived from the recovery execution so a crash after Booking commit is resumable without repeating the Reservation mutation.

Before a new Booking mutation, Booking validates stale source/target truth under its authoritative locks. Owner actions preserve owner authority: Recovery coordinates the workflow, but Catalog, Queue, Booking, Live Capacity and Communications perform or validate their own semantics through published contracts.

The current semantic authority is the accepted capability/guarantee set plus this ownership boundary. Historical F5/V3 documents remain provenance and may provide design rationale, but they do not override the current ownership map or executable dependency policy.
