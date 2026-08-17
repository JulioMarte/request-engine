# Request Engine V3 release gates

Status values:

- `PASS`: current-branch executable evidence satisfies the gate;
- `PARTIAL`: some evidence exists but the release gate is not closed;
- `MISSING`: required release proof has not been implemented.

A green historical workflow is evidence only for the exact commit/tree it tested. Final promotion to `main` must regenerate the evidence bundle on the final release candidate.

| Gate | Requirement | Status | Required proof before PASS |
|---|---|---:|---|
| G01 | V3 candidate and migration ordering | PASS | candidate SQL ordering/inventory architecture tests |
| G02 | Clean PostgreSQL 18 bootstrap | PASS | repeated clean bootstrap proof |
| G03 | V2 design-history preservation | PASS | canonical V2 history job |
| G04 | Python quality and architecture | PASS | Ruff, format, Pyright, security, dependency and architecture suite |
| G05 | Complete invariant registry | PARTIAL | every V3-Ixx must map to executable owner-boundary proof |
| G06 | Tenant/RLS isolation | PASS | real app LOGIN role, protected-function inventory, fail-closed RLS and attack matrix |
| G07 | Booking lifecycle | PASS | complete booking lifecycle including capacity/recovery/communication consequences |
| G08 | Slot recovery | PASS | complete Opportunity/Offer/Hold/accept/decline/expiry/candidate proof |
| G09 | Worker concurrency/fencing | PARTIAL | multi-worker claim/fencing/crash/reclaim proof |
| G10 | Crash/recovery semantics | PARTIAL | crash at authoritative/external-effect boundaries and deterministic recovery |
| G11 | Idempotency and retry semantics | PASS | frozen runtime command inventory + post-commit response-loss replay + fingerprint-conflict proof |
| G12 | Optimistic concurrency | PASS | real concurrent writers for every caller-selected revision-managed public aggregate |
| G13 | ProviderEvent/reconciliation | PARTIAL | duplicate/reorder/ambiguity/reconciliation/failure matrix |
| G14 | Runtime privilege contract | PASS | complete app/worker/admin/table/function/SECURITY DEFINER matrix |
| G15 | Query plans and index evidence | MISSING | representative-cardinality EXPLAIN/ANALYZE evidence for hot paths |
| G16 | Public API contract freeze | PARTIAL | final OpenAPI/capability/error snapshots on frozen candidate |
| G17 | `0001_initial` equivalence | MISSING | clean candidate-chain DB vs generated initial DB structural/behavioral equivalence |
| G18 | Unified adversarial/failure suite | MISSING | one release gate executing attack, race, crash, retry, order and mutation families |
| G19 | Fresh production-like bootstrap | PARTIAL | empty PostgreSQL 18 + production-style roles + app/worker + release suite |
| G20 | Final release artifact/manifest | MISSING | exact-head manifest with fingerprints, environment and all G01-G20 PASS |

## Phase 6E — idempotency and optimistic-concurrency closure

Phase 6E freezes the runtime mutation inventory in `docs/release/v3-idempotency-concurrency-inventory.md` and enforces it with `tests/architecture/test_retryable_command_inventory.py`.

G11 is `PASS` on the current branch because all fifteen runtime-available, non-internal mutating capabilities now have executable post-commit response-loss coverage. `appointments.book` is covered by the original R19 Booking proof; Request, Reservation mutation, attendance, Queue, Waitlist, SlotOffer and ReminderPlan commands are covered by the Phase 6E HTTP failure matrix. Each proof allows the real ASGI transaction to commit, drops the first response, retries the same `Idempotency-Key`, and asserts authoritative cardinality/state rather than merely checking the HTTP response. The shared PostgreSQL idempotency primitive continues to reject same identity + different fingerprint; Phase 6E additionally found and fixed the attendance-specific payload-dependent scope split through candidate migration `037-attendance-idempotency-scope-hardening.sql`.

G12 is `PASS` on the current branch because every caller-selected public revision-managed aggregate has real concurrent-writer evidence with application-runtime sessions and deliberate PostgreSQL lock barriers: Request, Reservation (cancel/reschedule and attendance), QueueEntry, WaitlistEntry, SlotOffer and ReminderPlan. The stale writer must lose on revision and cannot append dependent state. Phase 6E found and fixed Request's previous lifecycle-before-revision ordering and normalized attendance to authority → revision → lifecycle after the aggregate lock.

CI #896 (`31999091531`) on head `c7459454a5284ab295285bd0c4f463bb239f17b0` produced a `VALID` candidate evidence bundle before this registry-only reconciliation: 369 collected tests, 369 reverse-order passes, and three concurrency-stability rounds of 60 passes each. The registry reconciliation itself must also pass the canonical exact-head CI before PR integration. As with every current-branch `PASS`, final promotion to `main` still requires regeneration on the eventual frozen release candidate; a later weakening/removal of the inventory or proof returns G11/G12 to incomplete status.

## Deterministic race-closure evidence

The preceding race-closure phase added deterministic PostgreSQL/HTTP evidence for R08, R17, R18, R19 and R22 and exposed a least-privilege SlotOffer deferred-trigger defect that was fixed by migration `036-slot-offer-deferred-trigger-privilege-hardening.sql`. R19 became the seed for the broader Phase 6E G11 proof. R08 is now part of the completed G08 release claim and is promoted in the race matrix by the Phase 6K closure.

The race proofs use real runtime roles, independent sessions and explicit PostgreSQL overlap. They assert final cardinality and state, not merely an exception. Provider routing remains semantic and does not acquire direct Booking authority; Reminder cancellation and materialization continue to serialize under the authoritative plan/root locks.

## Post-integration baseline

PR #52 and the subsequent production-worker/reservation-delivery integrations materially strengthened the candidate before Phase 6 release closure. The post-merge rebaseline intentionally did not promote release gates merely because tests existed: a gate moves to `PASS` only when its complete frozen claim has executable current-branch evidence.

The integrated baseline includes real `request_engine_app` LOGIN-role HTTP coverage, adversarial RLS/privilege tests, worker lease/fencing primitives, Booking/Queue/Waitlist/Reminder verticals, ReservationAccess/Delivery, ProviderEvent handling and cross-tenant shared-capacity serialization. Those components remain subject to the unfinished gates above.

## Phase 6I — tenant/RLS and Party-authority closure

**G06 is `PASS`.** The gate is now backed by all four required evidence families on one exact branch head:

- **real app LOGIN:** integration and E2E proofs create LOGIN roles inheriting only `request_engine_app`, require non-superuser/NOBYPASSRLS runtime flags, serve tenant-scoped HTTP and deny `SET ROLE` escalation into worker/admin/schema-owner roles;
- **protected-function inventory:** `tests/db/test_v3_app_function_privilege_inventory.py` enumerates every function executable by a real app LOGIN in `request_engine`, `request_cmd` and `request_admin` and requires exact equality with the reviewed allowlist; any new executable function is release-visible drift;
- **fail-closed RLS:** adversarial DB tests require tenant policies on every tenant-owned table, prove missing organization context fails closed, and reject foreign reads/writes while `security_invoker` read surfaces preserve RLS;
- **attack matrix:** Booking, Requests, Queue, Waitlist and Reminders compare foreign identifiers with nonexistent controls, exact Party-authority primitives reject invalid temporal/state/scope combinations, and authenticated operator override cannot cross tenant boundaries.

The same Phase 6I work closes R23/R24 in `docs/release/v3-race-matrix.md`. It also corrected SlotOffer accept/decline authority ordering and normalized invalid Reminder Party references from an internal 500 fallback to an opaque tenant-reference error. These are correctness/security changes, not new product scope.

CI #905 (`32029659776`) on head `f6cec8e2c2b779d4b18f1a12195b52b0ffa15367` produced a `VALID` candidate evidence bundle with 392 collected tests across all 103 expected files, 392 reverse-order passes, three concurrency-stability rounds of 70 passes each, passing mutation probes and the exact real-LOGIN app function inventory. This registry reconciliation must itself pass canonical exact-head CI before integration.

## Runtime privilege closure

**G14 is `PASS`.** `docs/release/v3-runtime-privilege-inventory.md` freezes the complete runtime role contract and `tests/db/test_v3_runtime_privilege_closure.py` proves it using real LOGINs rather than group-role catalog assumptions.

The proof enumerates schema `USAGE/CREATE`, every relation privilege and the exact executable function set for `request_engine_app`, `request_engine_worker` and `request_engine_admin`. It verifies that app/worker cannot enter admin/schema-owner authority, that trusted admin BYPASSRLS is reachable only through explicit `SET ROLE request_engine_admin`, and that even admin cannot create Request Engine schema objects or become schema owner. Every current `SECURITY DEFINER` is dynamically audited for `request_engine_schema_owner` ownership, exact `pg_catalog, request_engine, pg_temp` search path and no `PUBLIC EXECUTE`.

Migration `038-runtime-privilege-closure.sql` removes stale worker grants for application idempotency and Party-authority primitives plus worker `request_read` usage. Production Worker Assembly already routes domain work through the separate app-role domain session; CI proves that removing those historical grants does not break worker/domain verticals.

CI #914 (`32034507295`) on head `90529b199064924561b61da5e2611d3c1ffdb78f` produced `VALID` artifact `9290385131` (`sha256:2b79a0fb702cb3f601bf80f68706eb8b30a2d5a97f0069c2950ff07d34de2f73`) bound to tree `100d55c00f32e389ae4930fb0af3e54838efba58`: 396 tests from all 104 expected files, 396/396 reverse-order passes, three 70-test concurrency-stability rounds, four passing mutation probes and zero test-quality errors/warnings. This registry-only promotion must itself pass canonical exact-head CI before integration.

## Phase 6K — Booking lifecycle and Slot Recovery closure

**G07 is `PASS`.** The release claim now covers the authoritative Reservation lifecycle and its durable consequences rather than only isolated Booking state transitions. Existing Booking integration tests prove creation, cancellation, reschedule, attendance/no-show and capacity-claim state transitions; Phase 6K adds `tests/integration/v3_reservation_lifecycle/test_reservation_lifecycle_outbox_composition.py`, which deliberately simulates partial committed lifecycle consequences and replays the same durable Reservation facts. Creation replay converges to one generation of Reservation scheduling and communications work. Cancellation replay cancels Reservation scheduling and communication tasks, then recovers the released slot exactly once through the existing SlotOpportunity -> Waitlist -> CapacityHold -> SlotOffer pipeline. Final task/action/opportunity/offer/hold cardinality and status are asserted.

Phase 6K also fixes a production provenance defect in delayed `reservation.rescheduled.v1` processing. Reschedule facts now preserve `old_location_id`, `old_start_at` and `old_end_at` before the Reservation moves. `tests/integration/v3_reservation_lifecycle/test_reschedule_outbox_release_provenance.py` executes A -> B -> C first, processes both reschedule facts only after the aggregate has reached C, and requires the A -> B event to recover A and the B -> C event to recover B while the authoritative Reservation remains at C. Slot recovery therefore consumes event-time released-slot provenance; scheduling, communications and access reconciliation continue to converge against current Reservation state.

**G08 is `PASS`.** The complete release proof now composes released-slot discovery with the already executable Slot Recovery state machine. `tests/integration/v3_slot_offer_recovery/test_slot_offer_recovery.py` proves atomic FIFO Hold+SlotOffer creation, one active offer under concurrent candidate selection, accept promotion into one confirmed Reservation with coherent Hold/Opportunity/Waitlist/CapacityClaim state, and decline/expiry release with advancement to the next candidate. `test_slot_offer_release_races.py` proves the terminal races and both semantic winner orders with final graph assertions. `test_released_slot_recovery_races.py` proves duplicate consumers of one Reservation release serialize to exactly one recovery coordination chain. The new lifecycle-composition and delayed-reschedule tests prove that this state machine is reached idempotently from durable Reservation facts and from the correct historical slot.

Canonical CI #923 (`32053071800`) passed on exact PR head `12f7d5ade26dd4b192afc3666c414556517294fd`: Python quality/architecture, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and the aggregate candidate-and-verticals check all succeeded. Artifact `v3-candidate-release-proof` `9295582134` (`sha256:d7ef7942015ada1247976db8c51a470fe95cf5831ef65f6f9180f7aa8d7db10e`) is bound to that head and reports `evidence_status: VALID`, `artifact_set_complete: true`, zero validation errors, 106/106 expected test files, 398 collected tests, 398/398 reverse-order passes, three concurrency-stability rounds of 70 passes, passing mutation probes and zero test-quality errors/warnings. `release_status` remains correctly `NOT_READY` because unrelated gates remain incomplete.

This documentation reconciliation changes the tested tree and therefore must itself survive canonical exact-head CI before PR #59 is merge-ready. Final `development -> main` promotion must rerun G07/G08 and R03-R08 on the eventual frozen candidate.

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its executable proof family and survives canonical CI. If later implementation changes weaken or invalidate that proof, the gate returns to `PARTIAL`/`MISSING` until regenerated.

Historical artifacts are supporting evidence, not release authority. The final release artifact must bind the exact commit/tree, PostgreSQL/Python environment, schema/migration/OpenAPI fingerprints and all gate results for the candidate that is actually promoted.

## Next execution order

With G06/G07/G08/G11/G12/G14 closed, the remaining proof work should proceed in dependency order rather than by feature novelty:

1. close worker concurrency/fencing and crash recovery (G09/G10);
2. close ProviderEvent/reconciliation and communications failure semantics (G13 plus remaining invariant/race dependencies);
3. freeze public API/error/capability contracts after correctness stops moving (G16);
4. build representative query-plan/performance evidence and only then freeze indexes (G15);
5. generate and prove `0001_initial` equivalence after the candidate is semantically/index frozen (G17);
6. execute the unified adversarial/failure gate (G18);
7. prove a fresh production-like environment (G19);
8. generate the exact-head final artifact/manifest and set `release_status: READY` only when every gate is `PASS` (G20).

Do not create/bless `0001_initial`, freeze indexes, or claim release readiness merely because G06/G07/G08/G11/G12/G14 are now closed.
