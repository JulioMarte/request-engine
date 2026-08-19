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
| G05 | Complete invariant registry | PASS | every V3-Ixx maps to executable owner-boundary proof; 66/66 registry reconciliation survives exact-head canonical CI |
| G06 | Tenant/RLS isolation | PASS | real app LOGIN role, protected-function inventory, fail-closed RLS and attack matrix |
| G07 | Booking lifecycle | PASS | complete booking lifecycle including capacity/recovery/communication consequences |
| G08 | Slot recovery | PASS | complete Opportunity/Offer/Hold/accept/decline/expiry/candidate proof |
| G09 | Worker concurrency/fencing | PASS | multi-worker claim/fencing/crash/reclaim proof |
| G10 | Crash/recovery semantics | PASS | crash at authoritative/external-effect boundaries and deterministic recovery |
| G11 | Idempotency and retry semantics | PASS | frozen runtime command inventory + post-commit response-loss replay + fingerprint-conflict proof |
| G12 | Optimistic concurrency | PASS | real concurrent writers for every caller-selected revision-managed public aggregate |
| G13 | ProviderEvent/reconciliation | PASS | duplicate/reorder/ambiguity/reconciliation/failure matrix |
| G14 | Runtime privilege contract | PASS | complete app/worker/admin/table/function/SECURITY DEFINER matrix |
| G15 | Query plans and index evidence | PASS | representative-cardinality EXPLAIN/ANALYZE evidence for worker, Queue/SlotOffer, Booking, Communications, Reservation lifecycle and shared-capacity hot paths |
| G16 | Public API contract freeze | PASS | final OpenAPI/capability/error snapshots on frozen candidate |
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

## G05 — complete invariant registry closure

**G05 is `PASS`.** `docs/release/v3-invariant-proof-registry.json` and `docs/release/v3-invariant-matrix.md` now agree on all `V3-I01..V3-I66` as `PASS`, with every row bound to an executable proof set at its canonical owner boundary. The closure includes the catalog-wide tenant-reference proof for I01, exact Request-version/lifecycle proofs for I10/I11, the authenticated provider callback trust boundary for I13, Booking capacity/release proofs for I15–I30, and explicit Communications/Reminder owner-boundary evidence for I44–I51.

Canonical exact-head CI #1071 (`32174705295`) passed all six required jobs on head `a1af8715134820936cbd530440fc1ae131489c43`. Artifact `v3-candidate-release-proof` `9338829019` (`sha256:acd8ef31b56f41f719470f82159c3cc799dd01917343205d7803658b16cedea9`) is bound to that PR head and reports `evidence_status: VALID`, `artifact_set_complete: true`, `missing_artifacts: []`, `validation_errors: []`, `working_tree_dirty: false`, passing catalog/concurrency/equivalence/mutation/schema/test/order/query-plan sub-artifacts, and zero test-quality errors or warnings. Its `release_status` remains correctly `NOT_READY` because G15–G20 are not all closed. This G05 promotion changes the release registry and therefore must itself survive one final exact-head canonical CI before PR #63 is merged.

## G15 — representative query-plan and index evidence

**G15 is `PASS`.** The candidate now measures the actual production SQL shapes at representative cardinality instead of treating schema index presence as proof. The canonical PostgreSQL 18 candidate job emits four independent query-plan artifacts: worker claims; Queue/Waitlist/SlotOffer; Booking availability/capacity; and operational Communications/Reservation/shared-capacity paths. Every proof uses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, rejects inappropriate sequential scans, enforces rows-removed/buffer/temp-I/O budgets, and binds production time windows before EXPLAIN where the runtime uses bind parameters.

The evidence drove three pre-baseline alignment migrations rather than a speculative index sweep. `041-slot-offer-history-query-plan-alignment.sql` bounds SlotOffer provenance lookups; `042-booking-query-plan-alignment.sql` adds active schedule, resource-exception and live local-capacity access paths; `043-operational-query-plan-alignment.sql` adds verified-contact lookup, subject-specific active ScheduledAction lookup, and the partial live-claim id access path required by cross-tenant shared-capacity conflict detection. An earlier range-only global CapacityClaim GiST was explicitly rejected after steady-state `VACUUM (ANALYZE)` still produced a historical Seq Scan; the final partial B-tree is therefore evidence-driven rather than retained merely because it existed in an earlier attempt.

Canonical CI #1125 (`32199955533`) passed the PostgreSQL 18 V3 candidate proof on implementation head `40276e8a02f4673c685e40af41ced8afafcb7597`. Artifact `v3-candidate-release-proof` `9347289531` (`sha256:8eb1fb0ecbd26f4d66b2574d5df5f0f877c06d6b8c784d7459f7b50f9ba6ca7d`) records the operational proof at four tenants with 1,500 rows/tenant of claim, Reservation, binding and reconciliation history. The seven operational probes all pass: latest delivery uses the existing delivery uniqueness index; verified contacts use `party_contact_points_verified_lookup_idx`; dispatch and reconciliation use `scheduled_actions_active_subject_idx`; Reservation status uses the tenant Reservation key plus `attendance_responses_current_idx`; root resolution uses the active-resource binding index; and shared-capacity conflict uses `capacity_claims_active_id_idx` plus `shared_capacity_claim_links_root_idx`. The previously pathological shared-capacity probe falls from 273 shared-hit blocks and 6,001 filtered CapacityClaims to 15 shared-hit blocks and one filtered claim, with no forbidden Seq Scan. Worker, Queue/SlotOffer and Booking plan families remain PASS in the same candidate artifact.

The executable evidence manifest now treats `.phase6/v3-operational-query-plans.json` as mandatory semantic evidence, validates all seven proof names, required selected indexes and representative cardinalities, and rejects non-PASS status, reported failures, forbidden sequential scans, shared reads or temporary writes. This G15 promotion therefore must itself survive canonical exact-head CI before PR #64 becomes merge-authoritative; final promotion to `main` must regenerate all G15 evidence on the frozen release candidate.

## G16 — public API contract freeze

**G16 is `PASS`.** The post-G15 candidate freezes the externally reviewable V3 contract at 24 classified `/v1/` operations, 34 canonical capability definitions on schema version `1`, and 51 public machine error codes. Architecture and E2E proofs compare independent reviewed baselines with the runtime capability registry and FastAPI/OpenAPI machine metadata; contract drift requires an intentional baseline diff rather than silently changing V3.

`scripts/release/prove_v3_public_api_contract.py` emits `.phase6/v3-public-api-contract.json`, and the canonical release manifest now treats it as mandatory semantic evidence. The manifest validator checks the exact operation/capability/OpenAPI cardinalities, schema versions and error-code inventory, validates both SHA-256 fingerprints and recomputes the embedded runtime-contract fingerprint before accepting the artifact.

Canonical CI #1138 (`32205998999`) passed all required jobs on exact implementation head `824b74836acdf6014e34a98ed931dcf21c07cfa1`. Artifact `v3-candidate-release-proof` `9349299370` (`sha256:b34aa22e91aa8974e62f7ad670e8dc34429835936676f3120c38f873995033f2`) reports `evidence_status: VALID`, `artifact_set_complete: true`, `missing_artifacts: []`, `validation_errors: []`, a clean working tree, and `artifact_validation.public_api_contract.status: PASS`. The public-contract artifact SHA is `83e5e76350c572e8bc879671b8fbf553ca19dff81aaec32cb527054c45111cad`; the proof reports 24 operations, 34 capabilities, schema versions `[1]`, 51 public machine error codes, 24 OpenAPI snapshots and `failures: []`.

The #1138 manifest intentionally still records G16 as `PARTIAL` because it predates this registry promotion. This promotion must therefore survive one final canonical exact-head CI before PR #65 is merge-authoritative. Final promotion to `main` must regenerate G16 evidence on the eventual frozen candidate.

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its executable proof family and survives canonical CI. If later implementation changes weaken or invalidate that proof, the gate returns to `PARTIAL`/`MISSING` until regenerated.

Historical artifacts are supporting evidence, not release authority. The final release artifact must bind the exact commit/tree, PostgreSQL/Python environment, schema/migration/OpenAPI fingerprints and all gate results for the candidate that is actually promoted.

## Next execution order

With G05–G16 closed, the remaining proof work should proceed in dependency order rather than by feature novelty:

1. execute the unified adversarial/failure gate across the stabilized pre-freeze candidate (G18);
2. prove a fresh production-like bootstrap with production-style roles and runtime processes (G19);
3. freeze the candidate only after G18/G19 survive without semantic or schema changes;
4. generate and prove final `0001_initial` structural/behavioral equivalence against that frozen candidate (G17);
5. rerun G18/G19 against the frozen candidate if the initial/freeze reconciliation changes any executable release input;
6. generate the exact-head final artifact/manifest and set `release_status: READY` only when every gate is `PASS` (G20).

Do not create/bless `0001_initial` before G18/G19 establish the production-like failure/bootstrap envelope, and do not claim release readiness merely because G05–G16 are now closed.
