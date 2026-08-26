# F5 Operational Recovery and Communications Contract

Status: normative feature contract for F5.

This document defines the semantics that MUST hold before and during implementation of the F5 `Operational Recovery and Communications` vertical slice described by `14-operational-intelligence-roadmap.md`.

## 1. Purpose

F5 answers a different question from F4.

F4 is authoritative for live-capacity projection: what operational capacity is executable, committed, active, queued, and still available at an authoritative snapshot.

F5 is authoritative only for recovery composition after that truth changes: which already-committed obligations are no longer satisfiable, which recovery alternatives are safe to propose, which explicit operator action was authorized, and how that action is linked to transactional communication intent/result.

F5 MUST NOT become a second schedule, availability, Reservation, Request, worker, or communications-delivery authority.

## 2. Owned domain terms

### 2.1 CapacityShortfallSummary

A derived, snapshot-bound assessment that compares executable capacity from F4 with already-committed Booking obligations for one operational context and time window.

A capacity reduction alone is not a material shortfall.

`material_shortfall = max(existing_commitment_demand - executable_capacity, 0)`

The implementation may use finer-grained duration/resource accounting when the Booking/F4 context requires it. The invariant is semantic: F5 MUST reuse the same authoritative capacity and commitment meanings that govern actual consumption; it MUST NOT invent an independent count-based availability algorithm.

If `material_shortfall == 0`, no recovery incident exists merely because capacity decreased.

### 2.2 AffectedReservationList

The deterministic set of confirmed Reservations whose commitments cannot be satisfied within the assessed authoritative capacity snapshot.

Membership MUST be reproducible from captured provenance. It MUST NOT be implemented as naive `reservation.start_at BETWEEN closed_start AND closed_end` logic when contextual supply/resource/location rules determine satisfiability.

Selection order MUST be deterministic and documented by the implementation. The first F5 slice uses stable ordering by commitment start and Reservation identity after authoritative context filtering; future prioritization policy requires a contract amendment.

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
- F4 source checkpoint/revision fingerprint;
- capacity values used to derive the shortfall;
- affected Reservation identities and expected revisions;
- proposed target slot/resource/location revision data required by Booking;
- a canonical payload fingerprint for idempotency/conflict checks.

Persisted JSON snapshots MUST be canonicalized before hashing. A proposal's source fingerprint is immutable.

## 6. Stale recovery protection — P0 invariant

An irreversible action MUST NOT execute from a stale recovery view.

Immediately before mutation, the command path MUST validate current authoritative state against the proposal's captured source checkpoint and each affected Reservation's expected revision. The target alternative MUST also be revalidated by Booking's normal reschedule authority.

If authoritative state has advanced in a way that invalidates the proposal, execution MUST fail with domain code `STALE_RECOVERY_PROPOSAL`, surfaced as HTTP 409 where an HTTP adapter exists.

The stale path MUST prove all of the following negative effects:

- zero Reservation mutation;
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
- explicit selected recovery move(s);
- idempotency key;
- expected proposal/source fingerprint.

Execution MUST delegate Reservation mutation to Booking's `RescheduleReservationCommand`/handler (or its owning public equivalent). F5 MUST NOT update Reservation rows directly.

For the first vertical slice, each selected Reservation move is an explicit Booking reschedule operation. Batch orchestration MAY be offered only if transaction semantics can guarantee the documented all-or-nothing behavior; otherwise the public command remains one affected commitment per execution action rather than pretending to provide atomic `reschedule all`.

## 8. Intake protection

F5 MUST NOT create a second availability authority.

`stop new intake from consuming already-broken capacity` means that after a closure/capacity loss, the same transactional Booking/capacity-consumption boundary used for normal holds/reservations MUST reject new consumption that is no longer executable.

If F4/Booking already enforce this from current schedule/supply truth, F5 REUSES and proves that behavior. A UI warning is not sufficient evidence. If a durable operational hold is later required for a policy not expressible by existing Booking authority, it must be owned/enforced by Booking and added by contract amendment.

## 9. Idempotency and concurrency

Recovery execution is an idempotent command.

Exact replay requires the same organization, actor/authorization context, proposal, selected action payload, and idempotency key. Exact replay returns the same logical result.

Reusing a key with a different canonical payload is an idempotency conflict and MUST NOT mutate state.

Concurrent identical executions MUST converge on one logical recovery action. At most one legal Reservation transition and one logical communication intent may be committed.

The implementation MUST use authoritative persistence/uniqueness/locking; process-local mutexes are not evidence.

## 10. Communication lineage and duplicate prevention

A successful recovery action may request a transactional notification only after the underlying domain mutation is committed/accepted by the authoritative transaction boundary.

The domain lineage is:

`RecoveryExecution -> Communications Intent -> Outbox/Delivery -> Provider Attempt -> Delivery Result`

The communication dedupe identity MUST be stable from the recovery execution identity plus recipient/purpose. HTTP retry, worker retry, concurrent worker claim, and repeated rendering of the same proposal MUST NOT create a second logical intent.

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
2. append-oriented/idempotent recovery execution fact.

The schema MUST NOT duplicate Reservation, schedule, capacity, outbox, or delivery state.

Tenant-owned F5 tables MUST carry Organization ownership and the repository's accepted RLS/privilege model.

## 14. Required acceptance proof

The acceptance suite MUST exercise authoritative persistence, not only mocked DTOs.

Scenario A — materiality and deterministic affected set:

- create executable capacity for 10 equivalent commitments;
- create 10 valid confirmed Reservations;
- introduce forced closed time/current supply change reducing executable capacity to 6;
- assert F4/Booking-derived shortfall is 4;
- assert the exact deterministic four affected Reservation identities and captured revisions;
- assert further intake into broken capacity cannot commit.

Scenario B — proposal is read-only:

- generate a proposal;
- prove alternatives are currently consumable through Booking authority;
- prove no Reservation changed and no communication intent exists.

Scenario C — stale view:

- mutate schedule/supply or an affected Reservation after proposal creation;
- execute the old proposal;
- assert `STALE_RECOVERY_PROPOSAL`/409 semantics;
- assert zero Reservation mutation caused by recovery and zero notification/outbox side effects.

Scenario D — idempotent execution and communications:

- create a current proposal;
- execute the same command twice and race identical executions where the integration harness permits;
- assert the legal Reservation transition occurred once;
- assert one recovery execution identity;
- assert one logical communication intent/dedupe identity;
- assert actor attribution and complete lineage to delivery result where provider simulation is supported;
- inspect authoritative final state.

HTTP 200/202 assertions, mock-called assertions, or affected-count-only assertions do not satisfy these gates.

## 15. Explicit non-goals

F5 v1 does not create:

- a generic RecoveryWorkflow engine;
- a replacement scheduler or capacity calculator;
- provider-specific communication logic;
- autonomous rescheduling without explicit authorization;
- optimization/ranking ML for recovery alternatives;
- a second analytics shortfall authority.

## 16. Completion gate

F5 is not complete until contract, old-to-new inventory, implementation, migration/schema, ownership docs, PostgreSQL-backed acceptance evidence, and exact-head CI evidence agree with this contract.
