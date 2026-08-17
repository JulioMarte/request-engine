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
| G09 | Worker concurrency/fencing | PASS | multi-worker claim/fencing/crash/reclaim proof |
| G10 | Crash/recovery semantics | PASS | crash at authoritative/external-effect boundaries and deterministic recovery |
| G11 | Idempotency and retry semantics | PASS | frozen runtime command inventory + post-commit response-loss replay + fingerprint-conflict proof |
| G12 | Optimistic concurrency | PASS | real concurrent writers for every caller-selected revision-managed public aggregate |
| G13 | ProviderEvent/reconciliation | PASS | duplicate/reorder/ambiguity/reconciliation/failure matrix |
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

Canonical CI #923 (`32053071800`) passed on exact implementation head `12f7d5ade26dd4b192afc3666c414556517294fd`: Python quality/architecture, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and the aggregate candidate-and-verticals check all succeeded. Artifact `v3-candidate-release-proof` `9295582134` (`sha256:d7ef7942015ada1247976db8c51a470fe95cf5831ef65f6f9180f7aa8d7db10e`) is bound to that head and reports `evidence_status: VALID`, `artifact_set_complete: true`, zero validation errors, 106/106 expected test files, 398 collected tests, 398/398 reverse-order passes, three concurrency-stability rounds of 70 passes, passing mutation probes and zero test-quality errors/warnings. `release_status` remains correctly `NOT_READY` because unrelated gates remain incomplete.

The release-registry reconciliation is intentionally documentation-only after that implementation proof. Its own exact-head canonical CI must pass before PR #59 is merge-ready; the final `development -> main` promotion must rerun G07/G08 and R03-R08 on the eventual frozen candidate.

## Phase 6F — worker concurrency/fencing and crash/recovery closure

**G09 is `PASS`.** `docs/release/v3-worker-fencing-crash-recovery-inventory.md` freezes the complete control surface for ScheduledAction, OutboxMessage and ProviderEvent. R12-R14 are exercised across all three durable families with independent `request_engine_worker` sessions, current-token assertions, expired-lease fencing, reclaim under a fresh token and stale complete/retry/dead-letter/renew rejection. R15 keeps both ScheduledAction cancellation/claim winner orders and additionally proves that a cancelled stale claim cannot pass the authoritative domain fence. R16 proves both Outbox completion/reclaim outcomes: a current completion prevents reclaim of delivered work, while an expired stale completion cannot finalize the replacement claimant even when the replacement claim transaction remains open. Rank-round tenant fairness is executable for all three work families; G15 remains responsible only for representative-cardinality performance of those queries.

**G10 is `PASS`.** The crash matrix covers every frozen failure boundary rather than treating lease expiry alone as crash recovery. Real subprocess tests `SIGKILL` a worker after durable claim for all three work families and require fresh-token reclaim with old-token fencing. Outbox replay proves an idempotent internal consequence can commit before publish failure and converge on retry. Reservation lifecycle composition proves independently committed authoritative business consequences converge when the durable fact is replayed. Communications and ReservationAccess both exercise external provider success followed by lease loss/local-finalization absence: the stale claimant cannot publish authoritative success, and the replacement claimant uses provider lookup/evidence instead of blindly creating a duplicate effect. Unit evidence covers processing timeout cancellation, heartbeat loss suppressing finalization, supervisor sibling cancellation/propagation and shared graceful-stop signaling. Existing retry/dead/admin-replay tests preserve database-clock scheduling, lifetime attempt history and audited privileged replay.

R20 deliberately remains `PARTIAL`. G10 closes the worker ownership/crash boundary for real external effects, but the complete provider duplicate/reorder/ambiguous-outcome/reconciliation and communications failure policy remains G13.

Canonical CI #946 (`32063335393`) passed on exact implementation head `7f61149999ab737b3f6089b135ff1a50d1e6187f`. Artifact `v3-candidate-release-proof` `9299172598` (`sha256:bf954de52a56fc6ace13ea76de4cade8732bb4c9a267cd5900ddf21324408dd7`) reports `evidence_status: VALID`, `artifact_set_complete: true`, zero validation errors and a clean tree. The manifest binds base `cc46234c9e3e1c3109b0aa87484d83cbefe28633`, implementation head `7f61149999ab737b3f6089b135ff1a50d1e6187f` and merge checkout/tested SHA `8e36d4e62a65df28d0ccb5d12843966da34bbf01`. It collected all 109 expected test files, recorded 409 reverse-order passes, three concurrency-stability rounds of 81 passes, four mutation probes killed as expected and zero test-quality errors/warnings. The artifact correctly remains `release_status: NOT_READY`.

This registry reconciliation changes documentation only; it must itself pass canonical exact-head CI before PR #60 is merge-authoritative. Final promotion to `main` must rerun G09/G10 and R12-R16 on the eventual frozen candidate.

## Phase 6G — ProviderEvent reconciliation and communications reliability closure

**G13 is `PASS`.** `docs/release/v3-provider-reconciliation-inventory.md` freezes the provider/reconciliation claim without inventing a universal provider state machine. ProviderEvent infrastructure owns durable identity, payload fingerprinting, routing and retry/reject/dead/replay; provider handlers translate inbound facts to semantic commands that revalidate current aggregate authority. Communications owns the concrete provider-correlated state machine and now proves send ambiguity, reconciliation-first recovery, accepted/ambiguous loops, retry/backoff, stale-worker fencing, terminal result ordering, ProviderEvent admin replay and Reminder occurrence reliability.

The Phase 6G audit found and fixed a production terminal-ordering defect that an earlier green run did not expose: two `reconcile_delivery` actions could both finish provider lookup, allowing `FAILED(non-retryable)` to emit `communication.task_failed.v1` and then a late `DELIVERED` result to overwrite the same Delivery/Task and emit `communication.task_completed.v1`. `finalize_provider_result()` now treats both `delivered` and non-retryable `failed` as absorbing terminal states for the same provider attempt. Retryable failure remains provisional and may recover to delivered because it has not emitted a terminal failure fact. A two-action/two-lookup E2E race deterministically forces failure-first/delivered-second and requires one failure fact, zero completion facts and a permanently failed Delivery/Task; a companion proof preserves late-delivery recovery for retryable failure.

The remaining matrix is executable on the same branch: duplicate ProviderEvent identity with payload conflict under real overlap; provider semantic command versus Reservation cancellation in both winner orders; send exception -> ambiguous + lookup-only reconciliation; lookup infrastructure failure without resend; crash after prepare and after provider finalization before ScheduledAction ack; lease loss during provider I/O; repeated accepted reconciliation without chain forking; NOT_FOUND -> retryable failure + future dispatch; retryable/non-retryable provider failure; trusted audited replay of dead/rejected ProviderEvents; deliberate concurrent Reminder occurrence materialization; and ReminderPlan cancellation versus leased occurrence.

Canonical CI #960 (`32067492021`) passed on exact implementation head `7ca60020608c9e153dcede578767ca9969b2f98f`: Python quality/architecture, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and candidate-and-verticals all succeeded. Artifact `v3-candidate-release-proof` `9300680212` (`sha256:d8cfb79d89f20dfac34bca906031bba5a6650011d6911b4d66c2befeca554839`) reports `evidence_status: VALID`, `artifact_set_complete: true`, zero validation errors and a clean tree. It binds base `cf98ac7da3b171d6dd42e0f77d91787b4450cc0c`, head `7ca60020608c9e153dcede578767ca9969b2f98f`, tested merge checkout `0e196a52b62e786e3d3200a9301f4be55e922f1d` and tree `d7c89c96a2e45ee4e8aaa6c4a67fa06a0edc3c92`. All 115 expected test files were collected, 419 tests passed in reverse order, three concurrency-stability rounds each passed 82 tests, all four mutation probes were killed and test quality reported zero errors/warnings. The artifact correctly remains `release_status: NOT_READY`.

R17, R18, R20, R21 and R22 are promoted in the race matrix by this same proof. This registry-only reconciliation must itself pass canonical exact-head CI before PR #61 is merge-authoritative. Final promotion to `main` must rerun G13 and those races on the eventual frozen candidate.

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its executable proof family and survives canonical CI. If later implementation changes weaken or invalidate that proof, the gate returns to `PARTIAL`/`MISSING` until regenerated.

Historical artifacts are supporting evidence, not release authority. The final release artifact must bind the exact commit/tree, PostgreSQL/Python environment, schema/migration/OpenAPI fingerprints and all gate results for the candidate that is actually promoted.

## Next execution order

With G06/G07/G08/G09/G10/G11/G12/G13/G14 closed, the remaining proof work should proceed in dependency order rather than by feature novelty:

1. reconcile and close the complete invariant registry (G05) now that the correctness/failure families have stopped moving;
2. freeze public API/error/capability contracts after correctness stops moving (G16);
3. build representative query-plan/performance evidence and only then freeze indexes (G15);
4. generate and prove `0001_initial` equivalence after the candidate is semantically/index frozen (G17);
5. execute the unified adversarial/failure gate (G18);
6. prove a fresh production-like environment (G19);
7. generate the exact-head final artifact/manifest and set `release_status: READY` only when every gate is `PASS` (G20).

Do not create/bless `0001_initial`, freeze indexes, or claim release readiness merely because G06/G07/G08/G09/G10/G11/G12/G13/G14 are now closed.