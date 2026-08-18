# Request Engine V3 invariant release matrix

Status: Phase 6 proof inventory.

The normative invariant definitions and ownership are in `docs/v3/02-pre-sql-contract.md`. This matrix intentionally references those IDs instead of redefining their semantics.

`PARTIAL` means relevant implementation or tests exist, but the Phase 6 release proof is not yet complete. `UNPROVEN` means a specific release proof has not yet been identified. `PASS` requires current-branch executable evidence.

| Invariant | Canonical owner class | Baseline evidence family | Baseline | Release proof phase |
|---|---|---|---|---|
| V3-I01 | DB | tenant authority + adversarial app-role DB/HTTP tests | PARTIAL | 6C/6I |
| V3-I02 | APP | adversarial HTTP Request/Booking/Queue/Waitlist authority tests | PARTIAL | 6I/6K |
| V3-I03 | APP | material Request authority/revocation race + authority HTTP tests | PARTIAL | 6I/6K |
| V3-I04 | DB/ops | exact real-login runtime role/privilege + SECURITY DEFINER matrix | PASS | 6I |
| V3-I05 | DB | adversarial RLS catalog/fail-closed app-role tests | PARTIAL | 6I |
| V3-I06 | BOTH | trusted execution provenance DB test | PARTIAL | 6I/6J |
| V3-I07 | BOTH | referenced OfferingVersion UPDATE/DELETE immutability regression | PASS | 6C/6K |
| V3-I08 | DB | relational tenant keys + foreign-reference adversarial tests | PARTIAL | 6C/6I |
| V3-I09 | BOTH | booking availability/resource adapters | PARTIAL | 6D/6E |
| V3-I10 | APP+DB reference | requests core + schema validation tests | PARTIAL | 6D/6K |
| V3-I11 | BOTH | requests core tests | PARTIAL | 6D/6E |
| V3-I12 | BOTH | idempotency error contract + frozen runtime fingerprint-conflict coverage | PASS | 6E |
| V3-I13 | APP | adversarial authority/operator-override/security boundaries | PARTIAL | 6I/6J |
| V3-I14 | APP | request cancellation implementation | PARTIAL | 6D/6K |
| V3-I15 | DB | booking commitment/candidate DB tests | PARTIAL | 6D/6L |
| V3-I16 | DB | capacity hardening + commitment tests | PARTIAL | 6D |
| V3-I17 | BOTH | booking commitment concurrency coverage | PARTIAL | 6D |
| V3-I18 | BOTH | booking commitment capacity coverage | PARTIAL | 6D |
| V3-I19 | transaction+BOTH | booking commitment vertical | PARTIAL | 6D |
| V3-I20 | BOTH | hold/booking implementation | PARTIAL | 6D/6L |
| V3-I21 | BOTH | booking commitment vertical | PARTIAL | 6D |
| V3-I22 | BOTH | hold confirmation/commitment tests | PARTIAL | 6D |
| V3-I23 | transaction+DB | reservation command/lifecycle tests | PARTIAL | 6D |
| V3-I24 | BOTH | reschedule booking core coverage | PARTIAL | 6D |
| V3-I25 | transaction | reschedule booking core coverage | PARTIAL | 6D |
| V3-I26 | APP protocol | deterministic inverse-input Booking resource-lock ordering regression | PASS | 6D/6L |
| V3-I27 | APP | post-lock availability/schedule revalidation regression | PASS | 6D |
| V3-I28 | BOTH | reservation lifecycle tests | PARTIAL | 6D |
| V3-I29 | domain/DB | reservation lifecycle/attendance tests | PARTIAL | 6K |
| V3-I30 | APP | lifecycle policy tests | PARTIAL | 6K/6L |
| V3-I31 | DB | DB unique constraint rejects second active subject entry | PASS | 6D |
| V3-I32 | APP under queue lock | FIFO CallNext ordered by admitted_at then id | PASS | 6D |
| V3-I33 | DB transaction/lock | concurrent CallNext returns distinct entries | PASS | 6D |
| V3-I34 | BOTH | queue command/HTTP tests | PARTIAL | 6D |
| V3-I35 | architecture | queue model/reader implementation | PARTIAL | 6A/6K |
| V3-I36 | model/DB | waitlist/slot recovery tests | PARTIAL | 6D |
| V3-I37 | APP | SlotOpportunity/booking boundary | PARTIAL | 6D |
| V3-I38 | DB | SlotOffer cardinality + duplicate released-slot recovery race | PARTIAL | 6D |
| V3-I39 | BOTH | slot-offer recovery vertical | PARTIAL | 6D |
| V3-I40 | transaction+BOTH | accept slot-offer recovery flow | PARTIAL | 6D |
| V3-I41 | transaction+BOTH | decline/expiry slot-offer flow | PARTIAL | 6D |
| V3-I42 | BOTH | SlotOpportunity source-event/idempotency serialization race | PARTIAL | 6D |
| V3-I43 | APP under opportunity lock | waitlist/slot selection implementation | PARTIAL | 6D/6G |
| V3-I44 | architecture/APP | durable communications ADR + vertical tests | PARTIAL | 6J |
| V3-I45 | BOTH | communication intent/dedupe implementation | PARTIAL | 6J |
| V3-I46 | BOTH/EXT | delivery store + communication delivery tests | PARTIAL | 6J |
| V3-I47 | APP | ProviderEventRouter → Booking semantic-command vs cancellation race | PARTIAL | 6J |
| V3-I48 | BOTH | ReminderPlan contract + schedule tests | PARTIAL | 6K/6L |
| V3-I49 | BOTH | reminder occurrence/replay + cancellation/materialization race | PARTIAL | 6J/6K |
| V3-I50 | BOTH | ReminderPlan cancellation vs leased occurrence materialization race | PARTIAL | 6J/6K |
| V3-I51 | product boundary/APP | V3 reminder product boundary | PARTIAL | 6K |
| V3-I52 | DB | worker runtime/lease tests | PARTIAL | 6F |
| V3-I53 | DB | expired-lease + communication fencing tests | PARTIAL | 6F |
| V3-I54 | BOTH | worker runtime/dead-letter implementation | PARTIAL | 6F |
| V3-I55 | architecture/APP | worker hardening contract/runtime | PARTIAL | 6F/6J |
| V3-I56 | BOTH | simultaneous ProviderEvent identity ingestion + payload-conflict race | PARTIAL | 6J |
| V3-I57 | EXT/APP | delivery worker/reconciliation contract | PARTIAL | 6F/6J |
| V3-I58 | transaction/APP | outbox pipeline and communication vertical | PARTIAL | 6J |
| V3-I59 | DB | trusted execution provenance DB test | PARTIAL | 6I/6J |
| V3-I60 | BOTH | frozen runtime post-commit response-loss/retry matrix | PASS | 6E |
| V3-I61 | BOTH | idempotency identity/fingerprint + canonical scope/replay contracts | PASS | 6E/6I |
| V3-I62 | BOTH/ops | request_admin authority events + UUID/no-enumeration adversarial tests | PARTIAL | 6I |
| V3-I63 | BOTH | cross-tenant CapacityClaim/Booking/Hold/SlotOffer integration + DB race tests | PARTIAL | 6D/6I |
| V3-I64 | DB+APP | private-table runtime privilege contract + opaque Booking error tests | PARTIAL | 6I/6K |
| V3-I65 | BOTH | binding activation/revocation/rebinding PostgreSQL race tests | PARTIAL | 6D/6I |
| V3-I66 | APP protocol + DB primitive | multi-root lock topology + simultaneous reschedule concurrency tests | PARTIAL | 6D/6L |

## Phase 6E idempotency / optimistic-concurrency evidence

Phase 6E closes the cross-cutting idempotency invariants whose canonical meaning is explicit in the pre-SQL contract:

- **V3-I12 — same idempotency key + different fingerprint is rejected.** The shared PostgreSQL idempotency primitive already enforced fingerprint binding. The frozen runtime command inventory proves every public mutating capability is idempotent, and the attendance regression found and removed the one payload-dependent scope split that could evade that binding. Migration `037-attendance-idempotency-scope-hardening.sql` normalizes historical attendance scopes, fails closed on historical collisions, and new attendance commands use the stable `booking.record_attendance_response` scope directly.
- **V3-I60 — idempotent retry cannot repeat an already committed business effect.** `appointments.book` retains the original R19 true response-loss proof. Phase 6E extends the same failure shape to Request submit/cancel, Reservation cancel/reschedule, attendance, Queue join/leave/call-next, Waitlist join/leave, SlotOffer accept/decline and ReminderPlan create/cancel. The custom ASGI transports allow the command transaction to commit before dropping the response, then require same-key replay plus command-specific durable cardinality assertions.
- **V3-I61 — identity is Organization + Principal + capability + fingerprint.** The architecture inventory freezes the runtime capability surface; centralized idempotency records enforce Organization/Principal/capability/key identity and fingerprint equality; the attendance defect demonstrated why capability scope itself must be stable and is now covered by an explicit regression.

Phase 6E also strengthens revision-managed aggregate correctness. Deterministic application-runtime races cover Request, Reservation cancel/reschedule, attendance, QueueEntry, WaitlistEntry, SlotOffer and ReminderPlan. Request exposed a real lifecycle-before-revision bug: a stale writer could receive `request_not_open` instead of revision conflict. Request mutation ordering is now lock → Party authority when applicable → revision → lifecycle. Attendance is similarly normalized to authority → revision → lifecycle after its Reservation lock, preventing lifecycle disclosure before subject authority and ensuring stale provider/business writers lose on revision.

CI #896 (`31999091531`) on head `c7459454a5284ab295285bd0c4f463bb239f17b0` produced `evidence_status: VALID`, collected 369 tests, passed all 369 in reverse order and passed three concurrency-stability rounds of 60 tests each. The registry-only reconciliation that promotes these invariant rows must itself pass canonical exact-head CI before integration. Final V3 promotion must regenerate the proofs after the remaining gates stop changing the candidate.

## Phase 6 race-closure evidence

The preceding deterministic race-closure work added real runtime-role evidence to invariant families that were missing explicit interleavings. R08 strengthens V3-I38/I42; R17 strengthens V3-I56; R18 strengthens V3-I47; R22 strengthens V3-I49/I50. Those rows remain `PARTIAL` because their wider owning release claims remain incomplete. R19 was initially a Booking-only proof for V3-I60/I61; the subsequent Phase 6E full command inventory is what allows V3-I60/I61 to move to `PASS`.

R18 now reflects the revision-first contract: when the provider semantic attendance command wins, cancellation loses on Reservation revision; when cancellation wins, the stale provider semantic command also loses on Reservation revision before lifecycle mutation and cannot append attendance or retain capacity. Provider routing still never writes Booking state directly.

## Post-integration evidence baseline

PR #52 exact-head CI #847 produced a complete, VALID candidate evidence bundle on the same Git tree that was merged into `development`: 340 release tests, all 340 in reverse order, and three repeated PostgreSQL/concurrency rounds with 47 tests per round. This proves the integrated evidence families were executable; it did not convert unrelated wider release claims to `PASS`.

## Cross-tenant shared-capacity extension evidence

V3-I62..V3-I66 have executable evidence for least-privilege denial of global-state enumeration, runtime-role/pre-RLS guard behavior, opaque cross-tenant conflict errors, simultaneous cross-tenant claim arbitration, Hold/Booking contention, SlotOffer/Booking winner orders, transactional reschedule rollback, binding activation/revocation races, unsafe rebind rejection, inverse multi-root locking and simultaneous real reschedules.

Those rows remain `PARTIAL` because feature integration and complete release proof are different claims. The final candidate must repeat them after correctness, privilege, performance, API-freeze and migration-equivalence work stops changing the candidate.

The extension preserves the original V3 ownership model: `Resource` remains tenant-local and `CapacityClaim` remains the only consumption ledger. `SharedCapacityIdentity` is an optional hidden serialization root for explicitly bound exclusive Resources, not a global Resource or second commitment ledger.

## Phase 6I tenant/Party-authority evidence

Phase 6I closes the release-level tenant-isolation gate G06 and races R23/R24 without pre-promoting the broader invariant registry. The current branch now has a real least-privileged app LOGIN, fail-closed RLS/catalog coverage, an exact executable app-function allowlist, deterministic revoke races for every distinct material Party scope, protected HTTP foreign-versus-nonexistent controls across Booking/Requests/Queue/Waitlist/Reminders, exact-scope temporal/state authority denial tests and tenant-bounded authenticated override proof.

The invariant rows above intentionally remain unchanged in this PR except where a later owner-boundary proof explicitly promotes one. Their canonical claims do not map one-to-one to G06/R23/R24: V3-I03 includes current Principal/Representation/**policy** revalidation; V3-I13 is specifically provider callback authentication/semantic binding; and G05 requires every invariant to be reviewed at its declared owner boundary. DB-owned V3-I01/I05/I08 also receive stronger evidence here, but promoting them opportunistically would mix Phase 6I gate closure with the separate complete-invariant-registry exercise.

CI #905 (`32029659776`) on head `f6cec8e2c2b779d4b18f1a12195b52b0ffa15367` produced `evidence_status: VALID`, collected all 392 tests from 103 expected files, passed 392/392 in reverse order, passed three concurrency-stability rounds of 70 tests and passed mutation probes. The subsequent registry reconciliation passed exact-head CI before Phase 6I integration. Final G05 work will reassess V3-I01..V3-I66 individually without weakening the Phase 6I proofs recorded here.

## Runtime privilege evidence

**V3-I04 is `PASS`.** Its canonical DB/ops claim is that runtime app/worker roles do not operate with schema-owner or superuser authority. Phase 6 G14 now proves that claim directly with real LOGIN roles and the complete PostgreSQL privilege catalog rather than relying on migration intent alone.

`tests/db/test_v3_runtime_privilege_closure.py` verifies app/worker/admin runtime identities, schema privileges, every relation privilege, exact executable function allowlists, role transition boundaries and all current `SECURITY DEFINER` routines. App and worker LOGINs start NOBYPASSRLS/NOSUPERUSER and cannot `SET ROLE` into admin or schema-owner. Trusted admin BYPASSRLS is only reached by explicitly entering `request_engine_admin`, while even that role cannot become schema owner or create Request Engine schema objects. Migration `038-runtime-privilege-closure.sql` removes stale worker domain grants that predated the Production Worker Assembly split.

CI #914 (`32034507295`) on head `90529b199064924561b61da5e2611d3c1ffdb78f` produced a `VALID`, complete artifact with 396/396 canonical and reverse-order tests, three 70/70 concurrency-stability rounds and passing mutation probes. This registry-only promotion must itself pass canonical exact-head CI before integration.

No other invariant is promoted by G14. In particular, G05 remains `PARTIAL` until all V3-I01..V3-I66 have owner-boundary proof individually reviewed and recorded.

## G05 direct invariant closure evidence

CI #980 (`32137750612`) on head `81fb36da44743273265c9dce6ffb7ca5c01589c9` produced a complete `VALID` artifact: 422/422 canonical tests, 422/422 reverse-order tests, 118/118 expected files, three passing concurrency-stability rounds, four passing mutation probes, and zero test-quality errors or warnings. The artifact preserves `release_status: NOT_READY` and G05 `PARTIAL`.

That evidence directly promotes these owner-boundary claims:

- **V3-I07 — OfferingVersion historical snapshot immutability.** `tests/db/test_v3_offering_version_immutability.py` creates a Reservation and complete CapacityClaim set atomically against a concrete OfferingVersion, then proves direct UPDATE and DELETE are rejected and the Reservation retains the original immutable snapshot reference.
- **V3-I26 — canonical Booking resource lock order.** `tests/integration/v3_booking_commitments/test_booking_lock_order.py` drives two real app-role transactions through `lock_resources()` with inverse input order and proves both serialize on the same UUID-sorted acquisition order without deadlock.
- **V3-I27 — post-lock availability revalidation.** `tests/integration/v3_booking_commitments/test_booking_schedule_revalidation.py` blocks Booking at the real Resource `FOR UPDATE`, commits a newly-unavailable schedule exception, then proves Booking re-reads availability after acquiring the lock, rejects the stale slot and leaves no Reservation or CapacityClaim.
- **V3-I31 — one active QueueEntry per queue/subject.** `tests/db/test_v3_candidate.py::test_queue_allows_only_one_active_entry_per_subject` inserts one active entry and proves PostgreSQL rejects a second active row for the same `(ServiceQueue, subject)` with the DB uniqueness backstop.
- **V3-I32 — deterministic FIFO CallNext.** `tests/integration/v3_first_vertical/test_business_and_queue.py::test_call_next_is_fifo_idempotent_and_emits_outbox` proves earlier `admitted_at` wins first and the command query orders by `(admitted_at,id)` while holding the queue root.
- **V3-I33 — concurrent CallNext cannot select the same entry.** `tests/integration/v3_first_vertical/test_business_and_queue.py::test_concurrent_call_next_never_returns_same_entry` runs two real concurrent commands against one queue and requires two distinct selected entry IDs.

I34 and I35 intentionally remain `PARTIAL`: allowed transition enforcement and the absence of an authoritative mutable queue-position counter still need dedicated release guardrails.

These promotions do not imply G05 completion; every remaining `PARTIAL` invariant still requires its own declared owner-boundary proof.

## Release-proof rule

Each row must eventually point to executable proof that exercises the owner boundary named by the canonical contract. An application-only test is insufficient for a DB-owned invariant. A mocked concurrency test is insufficient for a lock, RLS, range-overlap, lease or fencing invariant.

The matrix may become more specific as Phase 6 adds proof files. It must not silently change the meaning or ownership of a `V3-Ixx`; such a change belongs in the canonical V3 contract first.
