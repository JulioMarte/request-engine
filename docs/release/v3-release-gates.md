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
| G06 | Tenant/RLS isolation | PARTIAL | real app LOGIN role, protected-function inventory, fail-closed RLS and attack matrix |
| G07 | Booking lifecycle | PARTIAL | complete booking lifecycle including capacity/recovery/communication consequences |
| G08 | Slot recovery | PARTIAL | complete Opportunity/Offer/Hold/accept/decline/expiry/candidate proof |
| G09 | Worker concurrency/fencing | PARTIAL | multi-worker claim/fencing/crash/reclaim proof |
| G10 | Crash/recovery semantics | PARTIAL | crash at authoritative/external-effect boundaries and deterministic recovery |
| G11 | Idempotency and retry semantics | PASS | frozen runtime command inventory + post-commit response-loss replay + fingerprint-conflict proof |
| G12 | Optimistic concurrency | PASS | real concurrent writers for every caller-selected revision-managed public aggregate |
| G13 | ProviderEvent/reconciliation | PARTIAL | duplicate/reorder/ambiguity/reconciliation/failure matrix |
| G14 | Runtime privilege contract | PARTIAL | complete app/worker/admin/table/function/SECURITY DEFINER matrix |
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

The preceding race-closure phase added deterministic PostgreSQL/HTTP evidence for R08, R17, R18, R19 and R22 and exposed a least-privilege SlotOffer deferred-trigger defect that was fixed by migration `036-slot-offer-deferred-trigger-privilege-hardening.sql`. R08/R17/R18/R22 still strengthen their wider owning gates without independently closing them. R19 became the seed for the broader Phase 6E G11 proof and is now covered across the frozen runtime command inventory.

The race proofs use real runtime roles, independent sessions and explicit PostgreSQL overlap. They assert final cardinality and state, not merely an exception. Provider routing remains semantic and does not acquire direct Booking authority; Reminder cancellation and materialization continue to serialize under the authoritative plan/root locks.

## Post-integration baseline

PR #52 and the subsequent production-worker/reservation-delivery integrations materially strengthened the candidate before Phase 6 release closure. The post-merge rebaseline intentionally did not promote release gates merely because tests existed: a gate moves to `PASS` only when its complete frozen claim has executable current-branch evidence.

The integrated baseline includes real `request_engine_app` LOGIN-role HTTP coverage, adversarial RLS/privilege tests, worker lease/fencing primitives, Booking/Queue/Waitlist/Reminder verticals, ReservationAccess/Delivery, ProviderEvent handling and cross-tenant shared-capacity serialization. Those components remain subject to the unfinished gates above.

## Promotion rule

A gate changes to `PASS` only in the same change set that identifies its executable proof family and survives canonical CI. If later implementation changes weaken or invalidate that proof, the gate returns to `PARTIAL`/`MISSING` until regenerated.

Historical artifacts are supporting evidence, not release authority. The final release artifact must bind the exact commit/tree, PostgreSQL/Python environment, schema/migration/OpenAPI fingerprints and all gate results for the candidate that is actually promoted.

## Next execution order

With G11/G12 closed, the remaining proof work should proceed in dependency order rather than by feature novelty:

1. finish tenant/Party authority and runtime privilege closure (G06/G14);
2. complete Booking and Slot Recovery vertical release proofs (G07/G08);
3. close worker concurrency/fencing and crash recovery (G09/G10);
4. close ProviderEvent/reconciliation and communications failure semantics (G13 plus remaining invariant/race dependencies);
5. freeze public API/error/capability contracts after correctness stops moving (G16);
6. build representative query-plan/performance evidence and only then freeze indexes (G15);
7. generate and prove `0001_initial` equivalence after the candidate is semantically/index frozen (G17);
8. execute the unified adversarial/failure gate (G18);
9. prove a fresh production-like environment (G19);
10. generate the exact-head final artifact/manifest and set `release_status: READY` only when every gate is `PASS` (G20).

Do not create/bless `0001_initial`, freeze indexes, or claim release readiness merely because G11/G12 are now closed.