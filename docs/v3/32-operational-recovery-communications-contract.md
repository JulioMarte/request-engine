# F5 Operational Recovery and Communications Contract

Status: normative feature contract for the explicit F5 recovery core slice.

This document defines the semantics that MUST hold for the F5 `Operational Recovery and Communications` slice described by `14-operational-intelligence-roadmap.md`. The broader original recovery roadmap is preserved, with explicit delivered/deferred disposition in `33-operational-recovery-old-new-disposition.md`; this contract must not be used to retroactively claim that deferred roadmap capabilities were delivered.

## 1. Purpose

F5 answers a different question from F4.

F4 is authoritative for live-capacity projection: what operational capacity is executable, committed, active, queued, and still available at an authoritative snapshot.

F5 is authoritative only for recovery composition after that truth changes: which already-committed obligations are no longer satisfiable, which recovery alternatives are safe to propose, which explicit operator action was authorized, and how that action is linked to transactional communication intent/result.

F5 MUST NOT become a second schedule, availability, Reservation, Request, worker, or communications-delivery authority.

## 2. Owned domain terms

### 2.1 CapacityShortfallSummary

A derived, snapshot-bound assessment that reuses the canonical F4 projection over Booking commitments plus deduplicated Queue/ServiceSession/planned workload.

F5 MUST use the same F4 assembly semantics used by the staff live-capacity projection, including active/queued/planned deduplication, workload estimates, open interruption state and open resource activity. F5 MUST NOT discard live work and then call the result operational recovery.

Two pressures are kept distinct:

```text
scheduled_shortfall = max(scheduled_committed_workload - executable_capacity, 0)
live_shortfall      = max(projected_remaining_workload - executable_capacity, 0)
material_shortfall  = max(scheduled_shortfall, live_shortfall)
live_pressure       = max(material_shortfall - scheduled_shortfall, 0)
```

When F4 cannot produce a known projected workload, scheduled shortfall remains the fail-closed materiality floor; uncertainty is not silently converted into known live pressure.

A capacity reduction alone is not a material shortfall. If `material_shortfall == 0`, no recovery incident exists merely because capacity decreased.

### 2.2 AffectedReservationList

The deterministic set of confirmed Reservations operationally displaced by the assessed authoritative snapshot.

Structural schedule/capacity loss MUST NOT be implemented by adding Reservations until their durations numerically fill the shortfall. A structurally affected Reservation is one whose captured planned commitment no longer fits any authoritative remaining operational interval.

Incremental `live_pressure` caused by deduplicated active/queued work may displace otherwise structurally fitting future commitments. The current policy selects latest still-planned commitments backwards until that incremental pressure is absorbed, because already-running/waiting work consumes the remaining day before later commitments. This order is deterministic and must remain contract-tested; changing prioritization requires a contract amendment.

Membership MUST be reproducible from captured provenance. It MUST NOT be implemented as naive `reservation.start_at BETWEEN closed_start AND closed_end` logic when contextual supply/resource/location rules determine satisfiability.

### 2.3 RescheduleProposal

An immutable, snapshot-bound suggestion to move one or more affected Reservations to alternatives that were genuinely consumable when proposed.

A proposal is not a command and MUST produce zero Reservation mutation, zero capacity mutation, and zero communication intent.

Each proposed move carries enough Booking data to execute through Booking's existing reschedule authority, including expected Reservation revision and the target resource choices/revisions required by Booking.

### 2.4 OperationalNotification

F5's domain-facing reference to a recovery communication intent/result. Communications remains authoritative for transactional communication intent, outbox deduplication, provider attempts, and delivery facts.

F5 persists or exposes only lineage sufficient to answer: which recovery action caused which Communications intent/result.

## 3. Ownership and dependency direction

The `operational_recovery` module MAY depend on public contracts of:

- `live_capacity` for authoritative projection/snapshot provenance;
- `booking` for Reservation snapshots, availability alternatives, and legal reschedule commands;
- `communications` for transactional communication intent creation and delivery-result references;
- shared idempotency/audit primitives where those are already public infrastructure.

The reverse dependency is forbidden. Booking, Live Capacity, and Communications MUST NOT import F5 domain code.

F5 MUST NOT import another module's database adapters or tables directly to bypass a public contract. Where an authority is missing a public read/mutation needed by F5, that owning module MUST expose the narrow contract.

## 4. Query / command boundary

Read/query paths may:

- assess a material shortfall;
- list affected Reservations;
- generate/persist an immutable proposal snapshot;
- return provenance and freshness metadata.

Read/query paths MUST NOT:

- reschedule a Reservation;
- send or enqueue a communication;
- mutate intake capacity;
- implicitly authorize recovery.

The only F5 irreversible path in v1 is an explicit recovery execution command.

## 5. Snapshot provenance

Every persisted recovery proposal MUST capture a replayable input snapshot sufficient to reject stale execution and explain the assessment later.

At minimum it contains:

- `as_of` in UTC;
- organization and operational context identity;
- assessed time-window bounds and facility timezone where relevant;
- F4 policy/resource/location revisions;
- canonical remaining operational intervals;
- scheduled Booking commitment identities/revisions/times;
- deduplicated live work identity, estimate/duration and active-service progress used by F4;
- open interruption/resource-activity blocker state;
- capacity/workload values used to derive the shortfall;
- affected Reservation identities and expected revisions;
- proposed target slot/resource/location revision data required by Booking;
- a canonical payload fingerprint for idempotency/conflict checks.

Persisted JSON snapshots MUST be canonicalized before hashing. A proposal's source fingerprint is immutable. Any material change to one of the authoritative inputs above MUST alter the source fingerprint.

## 6. Stale recovery protection — P0 invariant

An irreversible action MUST NOT execute from a stale recovery view.

Immediately before mutation, the command path MUST validate current authoritative state against the proposal's captured source checkpoint and each affected Reservation's expected revision. The target alternative MUST also be revalidated by Booking's normal reschedule authority.

F5 fingerprint validation is defense in depth; Booking's transactional source/revision/target guards remain mandatory and MUST reject source changes even on retry/recovery after a prepared F5 execution fact already exists.

If authoritative state has advanced in a way that invalidates the proposal, execution MUST fail with domain code `STALE_RECOVERY_PROPOSAL`, surfaced as HTTP 409 where an HTTP adapter exists.

The stale path MUST prove all of the following negative effects:

- zero Reservation mutation caused by recovery;
- zero recovery execution fact marked successful;
- zero communication intent created;
- zero outbox delivery created.

A server MUST NOT silently refresh the proposal and continue under the old operator authorization.

## 7. Recovery execution

V1 is a one-shot operational command path, not a workflow engine.

The command MUST include:

- organization identity;
- actor/principal identity;
- proposal identity;
- explicit selected recovery move;
- idempotency key;
- expected proposal/source fingerprint.

Execution MUST delegate Reservation mutation to Booking's `RescheduleReservationCommand`/handler (or its owning public equivalent). F5 MUST NOT update Reservation rows directly.

For the first vertical slice, each selected Reservation move is an explicit Booking reschedule operation. Batch orchestration MAY be offered only if transaction semantics can guarantee the documented all-or-nothing behavior; otherwise the public command remains one affected commitment per execution action rather than pretending to provide atomic `reschedule all`.

## 8. Intake protection

F5 MUST NOT create a second availability authority.

`stop new intake from consuming already-broken capacity` means that after a closure/capacity loss, the same transactional Booking/capacity-consumption boundary used for normal holds/reservations MUST reject new consumption that is no longer executable.

That reused behavior is not equivalent to an explicit operator command saying “stop intake even while capacity remains”. If the product requires that deliberate policy, Booking/operational configuration must own and enforce a typed command; it is not delivered implicitly by F5 v1.

## 9. Idempotency and concurrency

Recovery execution is an idempotent command.

Exact replay requires the same organization, actor/authorization context, proposal, selected action payload, and idempotency key. Exact replay returns the same logical result.

Reusing a key with a different canonical payload is an idempotency conflict and MUST NOT mutate state.

Concurrent identical executions MUST converge on one logical recovery action. At most one legal Reservation transition and one logical communication intent may be committed.

The implemented protocol relies on authoritative durable composition, not process-local mutexes and not a claimed advisory lock:

- F5 durable uniqueness for proposal/Reservation and actor/idempotency identity;
- stable `recovery:{execution_id}:booking:v1` Booking idempotency;
- Booking transactional source/revision revalidation and Reservation row/concurrency guards;
- conditional F5 terminal transitions;
- stable execution-derived Communications idempotency/dedupe;
- conditional one-time attachment of the same CommunicationTask identity.

If this protocol cannot pass a real PostgreSQL concurrency proof, the feature is not complete; documentation MUST NOT substitute an unimplemented lock primitive for that proof.

## 10. Communication lineage and duplicate prevention

A successful recovery action may request a transactional notification only after the underlying domain mutation is committed/accepted by the authoritative transaction boundary.

The domain lineage is:

`RecoveryExecution -> CommunicationTask -> Outbox/Delivery -> Provider Attempt -> Delivery Result`

The communication dedupe identity MUST be stable from the recovery execution identity plus recipient/purpose. HTTP retry, worker retry, concurrent execution, and repeated rendering of the same proposal MUST NOT create a second logical intent.

No provider/network I/O may occur while authoritative Booking locks are held.

## 11. Actor attribution and audit

Every irreversible recovery action MUST be attributable to the principal that explicitly authorized it.

Audit/recovery facts MUST preserve:

- actor/principal;
- proposal/source fingerprint;
- original Reservation revision and resulting revision/state;
- selected target;
- idempotency identity;
- Communications intent identity when requested;
- timestamps and terminal outcome.

System automation, if introduced later, MUST use an explicit system actor and cannot masquerade as a human operator.

## 12. Error semantics

Required semantic failures include:

- `RECOVERY_SHORTFALL_NOT_MATERIAL` — no positive shortfall exists;
- `RECOVERY_RESERVATION_NOT_AFFECTED` — requested commitment is not in the proposal;
- `RECOVERY_TARGET_UNAVAILABLE` — Booking rejects the target under current authority;
- `STALE_RECOVERY_PROPOSAL` — proposal/source/reservation revision no longer matches;
- `RECOVERY_IDEMPOTENCY_CONFLICT` — same key, different canonical command payload;
- ordinary tenant/authorization/not-found errors from owning boundaries.

Stale/idempotency mismatch map to conflict semantics, not generic 500 responses.

## 13. Persistence model

F5 v1 persists two concepts, not a generic workflow state machine:

1. immutable recovery proposal snapshot/provenance;
2. append-preserving/idempotent recovery execution fact.

The schema MUST NOT duplicate Reservation, schedule, capacity, outbox, or delivery state.

Tenant-owned F5 tables MUST carry Organization ownership and the repository's accepted RLS/privilege model.

## 14. Required acceptance proof

The acceptance suite MUST exercise authoritative persistence, not only mocked DTOs.

Scenario A — materiality and deterministic affected set:

- create executable capacity for 10 equivalent commitments;
- create 10 valid confirmed Reservations;
- introduce forced closed time/current supply change reducing executable capacity to 6;
- assert scheduled shortfall is 4;
- assert the exact deterministic structurally affected Reservation identities and captured revisions;
- separately create live Queue/ServiceSession pressure with scheduled commitments still fitting;
- assert F4/F5 materiality includes that live pressure and deterministically displaces the latest still-planned commitments;
- assert further intake into broken capacity cannot commit.

Scenario B — proposal is read-only:

- generate a proposal;
- prove alternatives are currently consumable through Booking authority;
- prove no Reservation changed and no communication intent exists.

Scenario C — stale view:

- mutate schedule/supply, live Queue/ServiceSession truth, or an affected Reservation after proposal creation;
- execute the old proposal;
- assert `STALE_RECOVERY_PROPOSAL`/409 semantics;
- assert zero Reservation mutation caused by recovery and zero notification/outbox side effects.

Scenario D — idempotent execution and communications:

- create a current proposal;
- execute the same command twice and race identical executions;
- assert the legal Reservation transition occurred once;
- assert one recovery execution identity;
- assert one logical CommunicationTask/dedupe identity;
- assert actor attribution and complete lineage to delivery result where provider simulation is supported;
- inspect authoritative final state.

HTTP 200/202 assertions, mock-called assertions, affected-count-only assertions, or a green aggregate suite without identifiable scenario assertions do not satisfy these gates.

## 15. Explicit non-goals and deferred roadmap capabilities

F5 v1 does not create:

- a generic RecoveryWorkflow engine;
- a replacement scheduler or capacity calculator;
- provider-specific communication logic;
- autonomous rescheduling without explicit authorization;
- optimization/ranking ML for recovery alternatives;
- a second analytics shortfall authority.

The following broader roadmap capabilities are **not delivered by this contract** and remain future product work unless an owner-controlled command already exists and is explicitly integrated later:

- automatic event-triggered recovery proposal/escalation;
- explicit operator stop-intake policy beyond natural Booking capacity enforcement;
- extend-day recovery execution via ScheduleException;
- generalized/contextual provider/resource replacement and contextual reschedule.

## 16. Completion gate

The explicit F5 recovery core slice is not complete until contract, old-to-new inventory, implementation, migration/schema, ownership docs, PostgreSQL-backed acceptance evidence, and exact-head CI evidence agree with this contract.

The broader original F5 roadmap is not complete merely because this narrower core slice is complete. Deferred capability status must remain visible in roadmap/disposition documentation.
