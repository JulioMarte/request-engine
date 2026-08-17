# Request Engine V3 release race matrix

Status: Phase 6 concurrency proof inventory.

The canonical transaction and lock rules are owned by `docs/v3/02-pre-sql-contract.md`. This matrix identifies the release-level interleavings that must have deterministic PostgreSQL evidence before freeze.

Status values describe current proof breadth. `PASS` means the named race has complete current-branch executable evidence for its frozen claim; final promotion still reruns the full matrix on the eventual release candidate.

| Race | Concurrent operations | Required winner/loser property | Baseline proof | Target |
|---|---|---|---|---|
| R01 | acquire capacity vs acquire same capacity | incompatible live consumption cannot both commit | PARTIAL | 6D |
| R02 | confirm Hold vs wall-clock expiry/expiry cleanup | either valid confirmation wins before expiry, or confirmation is rejected; never expired confirmation | PARTIAL | 6D/6L |
| R03 | Reservation cancel vs reschedule | one serialized lifecycle result; no leaked/replaced duplicate claims | PARTIAL | 6D |
| R04 | SlotOffer accept vs expire | exactly one terminal offer result; no Reservation plus next-candidate offer for same capacity | PARTIAL | 6D |
| R05 | SlotOffer accept vs decline | exactly one terminal offer result and one capacity consequence | PARTIAL | 6D |
| R06 | SlotOffer decline vs expire | exactly one release/advance consequence | PARTIAL | 6D |
| R07 | candidate selection vs candidate selection | one active offered SlotOffer per SlotOpportunity | PARTIAL | 6D |
| R08 | Reservation cancellation vs duplicate opportunity creation | one recovery coordination chain per source identity | PARTIAL | 6D/6E |
| R09 | CallNext vs CallNext | same QueueEntry cannot be called twice | PARTIAL | 6D |
| R10 | Request writer revision N vs writer revision N | one writer succeeds and one receives revision conflict | PASS | 6E |
| R11 | Reservation/booking writer revision N vs writer revision N | one authoritative mutation succeeds; stale writer cannot overwrite | PASS | 6E |
| R12 | worker claim vs worker claim | one current claim token per work item | PARTIAL | 6F |
| R13 | stale finalizer vs reclaimed worker | stale claim token cannot complete/retry/dead-letter reclaimed work | PARTIAL | 6F |
| R14 | late lease renewal vs reclaimed worker | expired owner cannot resurrect ownership | PARTIAL | 6F |
| R15 | ScheduledAction cancellation vs claim | one deterministic state transition; cancelled work cannot execute as authoritative new work | PARTIAL | 6F/6J |
| R16 | Outbox completion vs lease reclaim | stale publisher cannot finalize another claim | PARTIAL | 6F |
| R17 | ProviderEvent duplicate ingestion vs duplicate ingestion | one provider identity; different payload under same identity is conflict | PARTIAL | 6J |
| R18 | provider callback semantic command vs business cancellation | provider ordering cannot bypass current business authority/lifecycle | PARTIAL | 6J/6L |
| R19 | committed command response lost vs same idempotent retry | retry returns same logical effect without duplication | PASS | 6E |
| R20 | external side effect succeeds then worker crashes before local finalization | retry/reconciliation cannot create an uncontrolled duplicate semantic effect | PARTIAL | 6F/6J |
| R21 | reminder materialization vs same reminder materialization | occurrence identity dedupes duplicate future action creation | PARTIAL | 6J |
| R22 | ReminderPlan cancel vs occurrence materialization | obsolete future work cannot survive as valid current-plan work | PARTIAL | 6J |
| R23 | authority/revocation change vs material command | material command revalidates authority in its authoritative transaction | PARTIAL | 6I |
| R24 | tenant A request vs guessed tenant B aggregate ID | no cross-tenant read/write or existence oracle through protected surfaces | PARTIAL | 6I |
| R25 | tenant A capacity commitment vs tenant B overlapping commitment on one shared root | exactly one incompatible live commitment commits; loser exposes only generic unavailability | PARTIAL | 6D/6I |
| R26 | direct Booking vs cross-tenant Hold/SlotOffer in both winner orders | exactly one capacity owner; losing SlotOffer path leaves no false active offer or orphan Hold/Claim | PARTIAL | 6D/6L |
| R27 | reschedule vs foreign shared-capacity commitment | conflicting reschedule rolls back completely and original Reservation/claims remain authoritative | PARTIAL | 6D |
| R28 | binding activation/revocation vs live claim creation | one serialized authority/capacity outcome with correct backfill or preserved provenance | PARTIAL | 6D/6I |
| R29 | inverse multi-Resource/multi-shared-root acquisition, including simultaneous reschedules | local Resources lock before stable-ordered shared roots; no deadlock and final claim cardinality/state remains valid | PARTIAL | 6D/6L |

## Phase 6E optimistic-concurrency and response-loss evidence

**R10 is `PASS`.** `tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py::test_request_cancel_same_revision_has_one_winner_and_one_revision_conflict` starts two real app-runtime `requests.cancel` writers from the same observed Request revision behind a deliberate Request row-lock barrier. Exactly one returns success; the stale writer must return `revision_conflict`; the final Request is cancelled with revision advanced exactly once. Phase 6E also corrected the Request aggregate ordering used by record-result, complete and terminal mutations so revision validation precedes lifecycle validation after the root lock (and Party authority, when required). Existing terminal Request races now require `RequestRevisionConflict` for the stale same-revision writer while a later command using the current terminal revision still receives `RequestNotOpen`.

**R11 is `PASS`.** The same HTTP race file runs Reservation cancel versus reschedule from the same revision and accepted versus declined attendance responses from the same Reservation revision. Only one writer may advance the Reservation revision; the loser is a `revision_conflict`; final CapacityClaim/attendance cardinality is asserted. Separate deterministic runtime races cover QueueEntry leave, WaitlistEntry leave and ReminderPlan cancel, and `tests/integration/v3_slot_offer_recovery/test_slot_offer_runtime_revision_race.py` covers SlotOffer accept versus decline using the real application role. Together they close the full caller-selected public revision-managed aggregate inventory defined by Phase 6E.

**R19 is `PASS`.** The original Booking proof in `tests/integration/v3_first_vertical/test_http_idempotency_failure.py` remains the canonical create-Reservation example: the ASGI command commits, the transport drops the response, and the same-key retry must return the original Reservation with exactly one active CapacityClaim/idempotency result/outbox consequence. Phase 6E generalizes that failure shape to the rest of the frozen runtime mutation inventory through `test_http_request_idempotency_failure.py`, `test_http_reservation_idempotency_failure.py`, `test_http_attendance_idempotency_failure.py`, `test_http_queue_idempotency_failure.py`, `test_http_waitlist_idempotency_failure.py`, `test_http_slot_offer_idempotency_failure.py` and `test_http_reminder_idempotency_failure.py`. Every command asserts durable cardinality/state in addition to replay.

The expanded R19 proof exposed a real attendance idempotency defect: accepted and declined responses historically used payload-dependent idempotency scopes. Migration `037-attendance-idempotency-scope-hardening.sql` canonicalizes the scope to `booking.record_attendance_response`, fails closed if historical identities would collide, and keeps the response value in the command fingerprint. Same key + accepted followed by declined is now a deterministic `idempotency_conflict`, not two independent commands.

CI #896 (`31999091531`) on head `c7459454a5284ab295285bd0c4f463bb239f17b0` produced `evidence_status: VALID`, collected 369 tests, passed all 369 in reverse order and passed three concurrency-stability rounds of 60 tests each. This registry-only reconciliation must itself pass exact-head CI before integration; final V3 promotion reruns all race proofs after the remaining candidate work freezes.

## Phase 6 race-closure evidence

R08 is exercised by `tests/integration/v3_reservation_lifecycle/test_released_slot_recovery_races.py`. Two consumers of the same committed Reservation release are held behind the same real `waitlist.create_opportunity` idempotency row lock. After release, one transaction creates the recovery chain and the other replays it. The test requires one SlotOpportunity for the source event, one offered SlotOffer, one active CapacityHold/CapacityClaim chain and one completed idempotency identity.

R17 is exercised by `tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py`. One ProviderEvent insert is deliberately left uncommitted while a second independent tenant transaction attempts the same provider identity and is observed waiting on a PostgreSQL lock. Same-payload ingestion resolves to one row with one replay receipt; a different payload under the same identity resolves to `ProviderEventDedupeConflict` while preserving the first committed row.

R18 is exercised by `tests/integration/v3_reservation_lifecycle/test_provider_business_race.py`. A real `ProviderEventRouter` handler translates an inbound provider event into Booking's semantic attendance command while `CancelReservation` races behind the same Reservation row lock. If the provider semantic command wins, cancellation loses on Reservation revision and the Reservation/claim remain confirmed/active with one attendance response. If cancellation wins, the stale provider semantic command now also loses on Reservation revision before lifecycle mutation; it cannot append attendance or retain active capacity. Provider routing never writes Booking state directly.

R22 is exercised by `tests/integration/v3_first_vertical/test_reminder_plan_races.py`. A due ReminderPlan occurrence is genuinely leased, both cancellation and materialization are started behind the same ReminderPlan `FOR UPDATE` barrier, and both valid winner orders are enumerated. Cancellation-first makes the leased occurrence no-op as `plan_inactive`; materialization-first may create exactly one current occurrence task before cancellation, but cancellation removes every future pending ReminderPlan occurrence. No mixed state may leave an active plan or obsolete future recurrence after cancellation.

These R08/R17/R18/R22 rows remain `PARTIAL` because their named interleavings are only part of wider release gates that still include authority, provider-reconciliation or lifecycle failure families. R19 was initially in the same state but Phase 6E expanded it across the complete frozen runtime command inventory and therefore closes its specific claim.

## Post-integration reconciliation

The post-PR-#52 rebaseline inspected exact-head CI `#847` (`31983843624`) and its `v3-candidate-release-proof` artifact. That artifact collected 340 release tests, passed the reverse-order run with all 340 tests, and passed three repeated PostgreSQL/concurrency rounds of 47 tests each. The reconciliation changed a race from `TO VERIFY` only when an inspected test exercised the actual conflicting operations with deliberate overlap and asserted final state/cardinality.

R03 is `PARTIAL` based on `tests/integration/v3_booking_commitments/test_reservation_races.py::test_cancel_and_reschedule_serialize_to_one_reservation_revision`. The test starts cancel and reschedule behind the same real Reservation row lock, requires exactly one successful revision transition and one `ReservationRevisionConflict`, then asserts either the complete cancelled/no-active-claim graph or the complete rescheduled/one-active-claim graph.

R05 and R06 are `PARTIAL` based on `tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py`. Accept-vs-decline is forced behind the same SlotOpportunity lock and permits exactly one terminal winner; the final Offer/Hold/Opportunity/Reservation graph is asserted. Decline-vs-expire is exercised once expiry is due and asserts a single release/advance consequence and exactly one next active offer. The same file materially strengthens R04 by proving both the pre-expiry accept winner and post-expiry expiry winner semantic orders.

R15 is `PARTIAL` based on `tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py`. It proves both lock orders: cancellation first causes worker `SKIP LOCKED` discovery to skip the action, while claim first makes cancellation wait and then fences the stale claim token after cancellation commits. Both paths assert the terminal ScheduledAction row.

## Cross-tenant shared-capacity concurrency evidence

R25 has independent PostgreSQL connections deliberately overlapping on one hidden shared root and asserts exactly one winner plus one opaque `23P01` capacity-unavailable loser. R26 exercises Hold/Booking and SlotOffer/Booking in both ordering directions; the Booking-first SlotOffer proof requires a savepoint and asserts the opportunity closes without orphan speculative state. R27 proves rollback preserves the original Reservation and linked claim. R28 uses barriers around Resource/root authority mutation versus claim creation and validates link history. R29 combines an inverse multi-root SQL topology test with two real `RescheduleReservation` transactions synchronized immediately before the real protected shared-root lock call.

CI #847 consumed the cross-tenant inventory and repeated the concurrency selector successfully three times. R25-R29 remain `PARTIAL` here because this registry tracks wider release-proof closure on the release baseline rather than feature acceptance alone; the final release candidate still has to execute the complete gate set after all remaining Phase 6 work stops changing the candidate.

## Current Phase 6I tenant evidence

R23 has multiple independent evidence layers. `tests/db/test_v3_tenant_isolation_adversarial.py` proves both winner orders between Representation revocation and `lock_current_party_authority()` with independent PostgreSQL connections. HTTP authority-race suites additionally exercise material Request, Booking, Queue and Waitlist operations. R23 remains `PARTIAL` until every subject-scoped material mutation family named by the frozen contract has an equivalent deterministic authority-revalidation proof.

R24 has direct app-role, real-login and HTTP evidence. The DB suite proves fail-closed RLS behavior, foreign-row invisibility, foreign-write rejection, `security_invoker` read isolation, and foreign-versus-nonexistent authority lookups. The E2E/runtime suites prove an actual LOGIN role that inherits `request_engine_app`, is `NOBYPASSRLS`/non-superuser, can serve tenant-scoped HTTP, and cannot `SET ROLE` into worker/admin/schema-owner roles. Adversarial HTTP suites exercise Booking, Requests, Queue and Waitlist with foreign versus nonexistent controls. R24 remains `PARTIAL` until the remaining protected execution surfaces and release-level tenant attack inventory are explicitly closed on the final release baseline.

## Test construction rules

Release race tests must use independent PostgreSQL connections or sessions and deliberate barriers so the conflicting transactions overlap. Do not replace database races with mocks, threads that never overlap database transactions, or retry loops that hide the underlying interleaving.

Each completed race proof must assert both final cardinality and final state. A test is incomplete if it only asserts that one call raised an exception.

Where two outcomes are valid, the test must enumerate both valid state machines and reject every mixed state that violates a V3 invariant.

## Lock-order review

Phase 6D/6L must additionally record lock roots and order for commands that touch the same aggregates. The deadlock suite must deliberately attempt inverse acquisition where a code path could permit it. PostgreSQL deadlock victim selection is a safety net, not the intended concurrency protocol.