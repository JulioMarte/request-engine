# Request Engine V3 release race matrix

Status: Phase 6 concurrency proof inventory.

The canonical transaction and lock rules are owned by `docs/v3/02-pre-sql-contract.md`. This matrix identifies the release-level interleavings that must have deterministic PostgreSQL evidence before freeze.

Status values describe baseline proof breadth, not whether the implementation is believed correct.

| Race | Concurrent operations | Required winner/loser property | Baseline proof | Target |
|---|---|---|---|---|
| R01 | acquire capacity vs acquire same capacity | incompatible live consumption cannot both commit | PARTIAL | 6D |
| R02 | confirm Hold vs wall-clock expiry/expiry cleanup | either valid confirmation wins before expiry, or confirmation is rejected; never expired confirmation | PARTIAL | 6D/6L |
| R03 | Reservation cancel vs reschedule | one serialized lifecycle result; no leaked/replaced duplicate claims | PARTIAL | 6D |
| R04 | SlotOffer accept vs expire | exactly one terminal offer result; no Reservation plus next-candidate offer for same capacity | PARTIAL | 6D |
| R05 | SlotOffer accept vs decline | exactly one terminal offer result and one capacity consequence | PARTIAL | 6D |
| R06 | SlotOffer decline vs expire | exactly one release/advance consequence | PARTIAL | 6D |
| R07 | candidate selection vs candidate selection | one active offered SlotOffer per SlotOpportunity | PARTIAL | 6D |
| R08 | Reservation cancellation vs duplicate opportunity creation | one recovery coordination chain per source identity | TO VERIFY | 6D/6E |
| R09 | CallNext vs CallNext | same QueueEntry cannot be called twice | PARTIAL | 6D |
| R10 | Request writer revision N vs writer revision N | one writer succeeds and one receives revision conflict | PARTIAL | 6E |
| R11 | Reservation/booking writer revision N vs writer revision N | one authoritative mutation succeeds; stale writer cannot overwrite | PARTIAL | 6E |
| R12 | worker claim vs worker claim | one current claim token per work item | PARTIAL | 6F |
| R13 | stale finalizer vs reclaimed worker | stale claim token cannot complete/retry/dead-letter reclaimed work | PARTIAL | 6F |
| R14 | late lease renewal vs reclaimed worker | expired owner cannot resurrect ownership | PARTIAL | 6F |
| R15 | ScheduledAction cancellation vs claim | one deterministic state transition; cancelled work cannot execute as authoritative new work | PARTIAL | 6F/6J |
| R16 | Outbox completion vs lease reclaim | stale publisher cannot finalize another claim | PARTIAL | 6F |
| R17 | ProviderEvent duplicate ingestion vs duplicate ingestion | one provider identity; different payload under same identity is conflict | TO VERIFY | 6J |
| R18 | provider callback semantic command vs business cancellation | provider ordering cannot bypass current business authority/lifecycle | TO VERIFY | 6J/6L |
| R19 | committed command response lost vs same idempotent retry | retry returns same logical effect without duplication | MISSING | 6E |
| R20 | external side effect succeeds then worker crashes before local finalization | retry/reconciliation cannot create an uncontrolled duplicate semantic effect | PARTIAL | 6F/6J |
| R21 | reminder materialization vs same reminder materialization | occurrence identity dedupes duplicate future action creation | PARTIAL | 6J |
| R22 | ReminderPlan cancel vs occurrence materialization | obsolete future work cannot survive as valid current-plan work | TO VERIFY | 6J |
| R23 | authority/revocation change vs material command | material command revalidates authority in its authoritative transaction | PARTIAL | 6I |
| R24 | tenant A request vs guessed tenant B aggregate ID | no cross-tenant read/write or existence oracle through protected surfaces | PARTIAL | 6I |
| R25 | tenant A capacity commitment vs tenant B overlapping commitment on one shared root | exactly one incompatible live commitment commits; loser exposes only generic unavailability | PARTIAL | 6D/6I |
| R26 | direct Booking vs cross-tenant Hold/SlotOffer in both winner orders | exactly one capacity owner; losing SlotOffer path leaves no false active offer or orphan Hold/Claim | PARTIAL | 6D/6L |
| R27 | reschedule vs foreign shared-capacity commitment | conflicting reschedule rolls back completely and original Reservation/claims remain authoritative | PARTIAL | 6D |
| R28 | binding activation/revocation vs live claim creation | one serialized authority/capacity outcome with correct backfill or preserved provenance | PARTIAL | 6D/6I |
| R29 | inverse multi-Resource/multi-shared-root acquisition, including simultaneous reschedules | local Resources lock before stable-ordered shared roots; no deadlock and final claim cardinality/state remains valid | PARTIAL | 6D/6L |

## Post-integration reconciliation

The post-PR-#52 rebaseline inspected the exact-head CI `#847` (`31983843624`) and its `v3-candidate-release-proof` artifact. That artifact collected 340 release tests, passed the reverse-order run with all 340 tests, and passed three repeated PostgreSQL/concurrency rounds of 47 tests each. The reconciliation changes a race from `TO VERIFY` only when an inspected test exercises the actual conflicting operations with deliberate overlap and asserts final state/cardinality.

R03 is now `PARTIAL` based on `tests/integration/v3_booking_commitments/test_reservation_races.py::test_cancel_and_reschedule_serialize_to_one_reservation_revision`. The test starts cancel and reschedule behind the same real Reservation row lock, requires exactly one successful revision transition and one `ReservationRevisionConflict`, then asserts either the complete cancelled/no-active-claim graph or the complete rescheduled/one-active-claim graph.

R05 and R06 are now `PARTIAL` based on `tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py`. Accept-vs-decline is forced behind the same SlotOpportunity lock and permits exactly one terminal winner; the final Offer/Hold/Opportunity/Reservation graph is asserted. Decline-vs-expire is exercised once expiry is due and asserts a single release/advance consequence and exactly one next active offer. The same file also materially strengthens R04 by proving both the pre-expiry accept winner and post-expiry expiry winner semantic orders.

R15 is now `PARTIAL` based on `tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py`. It proves both lock orders: cancellation first causes worker `SKIP LOCKED` discovery to skip the action, while claim first makes cancellation wait and then fences the stale claim token after cancellation commits. Both paths assert the terminal ScheduledAction row.

R17 remains `TO VERIFY`. `test_provider_duplicate_replay_is_exact_and_payload_mutation_conflicts` proves deterministic sequential replay and payload-mutation conflict, but it does not yet force two simultaneous ingestion transactions to overlap on the provider identity.

R22 remains `TO VERIFY`. Existing reminder fencing proves that a stale ScheduledAction claim cannot perform a domain write, but that is not the same interleaving as ReminderPlan cancellation racing occurrence materialization.

R19 remains `MISSING`: ordinary duplicate/idempotency contract tests do not substitute for a committed command whose successful response is lost and then retried with the same key.

## Cross-tenant shared-capacity concurrency evidence

R25 has independent PostgreSQL connections deliberately overlapping on one hidden shared root and asserts exactly one winner plus one opaque `23P01` capacity-unavailable loser. R26 exercises Hold/Booking and SlotOffer/Booking in both ordering directions; the Booking-first SlotOffer proof requires a savepoint and asserts the opportunity closes without orphan speculative state. R27 proves rollback preserves the original Reservation and linked claim. R28 uses barriers around Resource/root authority mutation versus claim creation and validates link history. R29 combines an inverse multi-root SQL topology test with two real `RescheduleReservation` transactions synchronized immediately before the real protected shared-root lock call.

CI #847 has now consumed this updated cross-tenant inventory and repeated the concurrency selector successfully three times. R25-R29 remain `PARTIAL` here because this registry tracks wider release-proof closure on the release baseline rather than feature acceptance alone; the final release candidate still has to execute the complete gate set after all remaining Phase 6 work stops changing the candidate.

## Current Phase 6I tenant evidence

R23 has multiple independent evidence layers. `tests/db/test_v3_tenant_isolation_adversarial.py` proves both winner orders between Representation revocation and `lock_current_party_authority()` with independent PostgreSQL connections. HTTP authority-race suites additionally exercise material Request, Booking, Queue and Waitlist operations. R23 remains `PARTIAL` until every subject-scoped material mutation family named by the frozen contract has an equivalent deterministic authority-revalidation proof.

R24 has direct app-role, real-login and HTTP evidence. The DB suite proves fail-closed RLS behavior, foreign-row invisibility, foreign-write rejection, `security_invoker` read isolation, and foreign-versus-nonexistent authority lookups. The E2E/runtime suites prove an actual LOGIN role that inherits `request_engine_app`, is `NOBYPASSRLS`/non-superuser, can serve tenant-scoped HTTP, and cannot `SET ROLE` into worker/admin/schema-owner roles. Adversarial HTTP suites exercise Booking, Requests, Queue and Waitlist with foreign versus nonexistent controls. R24 remains `PARTIAL` until the remaining protected execution surfaces and release-level tenant attack inventory are explicitly closed on the final release baseline.

## Test construction rules

Release race tests must use independent PostgreSQL connections or sessions and deliberate barriers so the conflicting transactions overlap. Do not replace database races with mocks, threads that never overlap database transactions, or retry loops that hide the underlying interleaving.

Each completed race proof must assert both final cardinality and final state. A test is incomplete if it only asserts that one call raised an exception.

Where two outcomes are valid, the test must enumerate both valid state machines and reject every mixed state that violates a V3 invariant.

## Lock-order review

Phase 6D/6L must additionally record lock roots and order for commands that touch the same aggregates. The deadlock suite must deliberately attempt inverse acquisition where a code path could permit it. PostgreSQL deadlock victim selection is a safety net, not the intended concurrency protocol.
