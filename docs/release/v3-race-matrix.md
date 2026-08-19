# Request Engine V3 release race matrix

Status: Phase 6 concurrency proof inventory.

The canonical transaction and lock rules are owned by `docs/v3/02-pre-sql-contract.md`. This matrix identifies the release-level interleavings that must have deterministic PostgreSQL evidence before freeze.

Status values describe current proof breadth. `PASS` means the named race has complete current-branch executable evidence for its frozen claim; final promotion still reruns the full matrix on the eventual release candidate.

| Race | Concurrent operations | Required winner/loser property | Baseline proof | Target |
|---|---|---|---|---|
| R01 | acquire capacity vs acquire same capacity | incompatible live consumption cannot both commit | PASS | 6D |
| R02 | confirm Hold vs wall-clock expiry/expiry cleanup | either valid confirmation wins before expiry, or confirmation is rejected; never expired confirmation | PASS | 6D/6L |
| R03 | Reservation cancel vs reschedule | one serialized lifecycle result; no leaked/replaced duplicate claims | PASS | 6D |
| R04 | SlotOffer accept vs expire | exactly one terminal offer result; no Reservation plus next-candidate offer for same capacity | PASS | 6D |
| R05 | SlotOffer accept vs decline | exactly one terminal offer result and one capacity consequence | PASS | 6D |
| R06 | SlotOffer decline vs expire | exactly one release/advance consequence | PASS | 6D |
| R07 | candidate selection vs candidate selection | one active offered SlotOffer per SlotOpportunity | PASS | 6D |
| R08 | Reservation cancellation vs duplicate opportunity creation | one recovery coordination chain per source identity | PASS | 6D/6E |
| R09 | CallNext vs CallNext | same QueueEntry cannot be called twice | PASS | 6D |
| R10 | Request writer revision N vs writer revision N | one writer succeeds and one receives revision conflict | PASS | 6E |
| R11 | Reservation/booking writer revision N vs writer revision N | one authoritative mutation succeeds; stale writer cannot overwrite | PASS | 6E |
| R12 | worker claim vs worker claim | one current claim token per work item | PASS | 6F |
| R13 | stale finalizer vs reclaimed worker | stale claim token cannot complete/retry/dead-letter reclaimed work | PASS | 6F |
| R14 | late lease renewal vs reclaimed worker | expired owner cannot resurrect ownership | PASS | 6F |
| R15 | ScheduledAction cancellation vs claim | one deterministic state transition; cancelled work cannot execute as authoritative new work | PASS | 6F/6J |
| R16 | Outbox completion vs lease reclaim | stale publisher cannot finalize another claim | PASS | 6F |
| R17 | ProviderEvent duplicate ingestion vs duplicate ingestion | one provider identity; different payload under same identity is conflict | PASS | 6J |
| R18 | provider callback semantic command vs business cancellation | provider ordering cannot bypass current business authority/lifecycle | PASS | 6J/6L |
| R19 | committed command response lost vs same idempotent retry | retry returns same logical effect without duplication | PASS | 6E |
| R20 | external side effect succeeds then worker crashes before local finalization | retry/reconciliation cannot create an uncontrolled duplicate semantic effect | PASS | 6F/6J |
| R21 | reminder materialization vs same reminder materialization | occurrence identity dedupes duplicate future action creation | PASS | 6J |
| R22 | ReminderPlan cancel vs occurrence materialization | obsolete future work cannot survive as valid current-plan work | PASS | 6J |
| R23 | authority/revocation change vs material command | material command revalidates authority in its authoritative transaction | PASS | 6I |
| R24 | tenant A request vs guessed tenant B aggregate ID | no cross-tenant read/write or existence oracle through protected surfaces | PASS | 6I |
| R25 | tenant A capacity commitment vs tenant B overlapping commitment on one shared root | exactly one incompatible live commitment commits; loser exposes only generic unavailability | PASS | 6D/6I |
| R26 | direct Booking vs cross-tenant Hold/SlotOffer in both winner orders | exactly one capacity owner; losing SlotOffer path leaves no false active offer or orphan Hold/Claim | PASS | 6D/6L |
| R27 | reschedule vs foreign shared-capacity commitment | conflicting reschedule rolls back completely and original Reservation/claims remain authoritative | PASS | 6D |
| R28 | binding activation/revocation vs live claim creation | one serialized authority/capacity outcome with correct backfill or preserved provenance | PASS | 6D/6I |
| R29 | inverse multi-Resource/multi-shared-root acquisition, including simultaneous reschedules | local Resources lock before stable-ordered shared roots; no deadlock and final claim cardinality/state remains valid | PASS | 6D/6L |

## Phase 6E optimistic-concurrency and response-loss evidence

**R10 is `PASS`.** `tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py::test_request_cancel_same_revision_has_one_winner_and_one_revision_conflict` starts two real app-runtime `requests.cancel` writers from the same observed Request revision behind a deliberate Request row-lock barrier. Exactly one returns success; the stale writer must return `revision_conflict`; the final Request is cancelled with revision advanced exactly once. Phase 6E also corrected the Request aggregate ordering used by record-result, complete and terminal mutations so revision validation precedes lifecycle validation after the root lock (and Party authority, when required). Existing terminal Request races now require `RequestRevisionConflict` for the stale same-revision writer while a later command using the current terminal revision still receives `RequestNotOpen`.

**R11 is `PASS`.** The same HTTP race file runs Reservation cancel versus reschedule from the same revision and accepted versus declined attendance responses from the same Reservation revision. Only one writer may advance the Reservation revision; the loser is a `revision_conflict`; final CapacityClaim/attendance cardinality is asserted. Separate deterministic runtime races cover QueueEntry leave, WaitlistEntry leave and ReminderPlan cancel, and `tests/integration/v3_slot_offer_recovery/test_slot_offer_runtime_revision_race.py` covers SlotOffer accept versus decline using the real application role. Together they close the full caller-selected public revision-managed aggregate inventory defined by Phase 6E.

**R19 is `PASS`.** The original Booking proof in `tests/integration/v3_first_vertical/test_http_idempotency_failure.py` remains the canonical create-Reservation example: the ASGI command commits, the transport drops the response, and the same-key retry must return the original Reservation with exactly one active CapacityClaim/idempotency result/outbox consequence. Phase 6E generalizes that failure shape to the rest of the frozen runtime mutation inventory through `test_http_request_idempotency_failure.py`, `test_http_reservation_idempotency_failure.py`, `test_http_attendance_idempotency_failure.py`, `test_http_queue_idempotency_failure.py`, `test_http_waitlist_idempotency_failure.py`, `test_http_slot_offer_idempotency_failure.py` and `test_http_reminder_idempotency_failure.py`. Every command asserts durable cardinality/state in addition to replay.

The expanded R19 proof exposed a real attendance idempotency defect: accepted and declined responses historically used payload-dependent idempotency scopes. Migration `037-attendance-idempotency-scope-hardening.sql` canonicalizes the scope to `booking.record_attendance_response`, fails closed if historical identities would collide, and keeps the response value in the command fingerprint. Same key + accepted followed by declined is now a deterministic `idempotency_conflict`, not two independent commands.

CI #896 (`31999091531`) on head `c7459454a5284ab295285bd0c4f463bb239f17b0` produced `evidence_status: VALID`, collected 369 tests, passed all 369 in reverse order and passed three concurrency-stability rounds of 60 tests each. This registry-only reconciliation must itself pass exact-head CI before integration; final V3 promotion reruns all race proofs after the remaining candidate work freezes.

## Phase 6 race-closure evidence

R08 is exercised by `tests/integration/v3_reservation_lifecycle/test_released_slot_recovery_races.py`. Two consumers of the same committed Reservation release are held behind the same real `waitlist.create_opportunity` idempotency row lock. After release, one transaction creates the recovery chain and the other replays it. The test requires one SlotOpportunity for the source event, one offered SlotOffer, one active CapacityHold/CapacityClaim chain and one completed idempotency identity. Phase 6K composes this race with the complete Booking/Slot Recovery vertical and promotes R08 to `PASS`.

R17 is exercised by `tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py`. One ProviderEvent insert is deliberately left uncommitted while a second independent tenant transaction attempts the same provider identity and is observed waiting on a PostgreSQL lock. Same-payload ingestion resolves to one row with one replay receipt; a different payload under the same identity resolves to `ProviderEventDedupeConflict` while preserving the first committed row.

R18 is exercised by `tests/integration/v3_reservation_lifecycle/test_provider_business_race.py`. A real `ProviderEventRouter` handler translates an inbound provider event into Booking's semantic attendance command while `CancelReservation` races behind the same Reservation row lock. If the provider semantic command wins, cancellation loses on Reservation revision and the Reservation/claim remain confirmed/active with one attendance response. If cancellation wins, the stale provider semantic command now also loses on Reservation revision before lifecycle mutation; it cannot append attendance or retain active capacity. Provider routing never writes Booking state directly.

R22 is exercised by `tests/integration/v3_first_vertical/test_reminder_plan_races.py`. A due ReminderPlan occurrence is genuinely leased, both cancellation and materialization are started behind the same ReminderPlan `FOR UPDATE` barrier, and both valid winner orders are enumerated. Cancellation-first makes the leased occurrence no-op as `plan_inactive`; materialization-first may create exactly one current occurrence task before cancellation, but cancellation removes every future pending ReminderPlan occurrence. No mixed state may leave an active plan or obsolete future recurrence after cancellation.

At that stage R17/R18/R22 remained `PARTIAL` because their surrounding provider/reconciliation and communications-failure family was incomplete. Phase 6G closes that wider family and promotes them below; this historical section is retained as provenance rather than current status authority.

## Phase 6K Booking lifecycle / Slot Recovery race closure

**R03 is `PASS`.** `tests/integration/v3_booking_commitments/test_reservation_races.py::test_cancel_and_reschedule_serialize_to_one_reservation_revision` starts cancellation and reschedule behind the same real Reservation row lock. Exactly one revision transition succeeds and the loser receives `ReservationRevisionConflict`. The final graph is either a completely cancelled Reservation with no active claim or a completely rescheduled Reservation with exactly one active replacement claim; no mixed/leaked claim state is accepted. Phase 6K's lifecycle composition proof additionally demonstrates that the winning durable Reservation fact can be replayed after partial committed consequences without duplicating downstream schedule/communications/recovery state.

**R04 is `PASS`.** `tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py` proves both semantic sides of accept versus expiry. Before the stored deadline, accept remains authoritative and expiry cannot create a competing next-candidate result. Once the offer is actually expired on the database clock, expiry wins and accept is rejected. Final Offer/Hold/Opportunity/Reservation cardinality is asserted, including exactly one next active candidate after expiry.

**R05 is `PASS`.** The same race suite starts accept and decline behind the same Opportunity lock. Exactly one writer succeeds, the stale writer loses on SlotOffer revision, and the final graph is exclusively either accepted/consumed/filled with one Reservation and zero active offers, or declined/released/open with zero Reservation and one next active offer.

**R06 is `PASS`.** Decline and due expiry overlap behind the same authoritative Opportunity lock. Exactly one release/advance consequence survives, the original offer/hold become one coherent terminal pair and exactly one next candidate is offered. The test rejects double release or duplicate candidate advancement.

**R07 is `PASS`.** `tests/integration/v3_slot_offer_recovery/test_slot_offer_recovery.py::test_two_offer_workers_serialize_to_one_active_offer` runs two concurrent candidate-selection workers against the same SlotOpportunity. Both calls converge on the same SlotOffer id and FIFO WaitlistEntry, while PostgreSQL final state contains exactly one active offered SlotOffer. The same file proves that Hold and SlotOffer creation are atomic and accompanied by one expiry ScheduledAction and one communication intent.

**R08 is `PASS`.** The deterministic duplicate-release race remains the concurrency proof, and Phase 6K now closes its surrounding vertical: `test_reservation_lifecycle_outbox_composition.py` simulates partial committed cancellation consequences and handler replay, requiring cancellation of obsolete scheduling/communications plus exactly one recovered Opportunity/Offer/Hold/communication/expiry-action chain. `test_reschedule_outbox_release_provenance.py` separately proves delayed A -> B -> C reschedule facts recover their own event-time slots rather than mutable current Reservation/claim state.

Canonical CI #923 (`32053071800`) passed on exact PR head `12f7d5ade26dd4b192afc3666c414556517294fd`. Its `v3-candidate-release-proof` artifact `9295582134` (`sha256:d7ef7942015ada1247976db8c51a470fe95cf5831ef65f6f9180f7aa8d7db10e`) reports `evidence_status: VALID`, all 106 expected test files collected, 398 reverse-order passes, three concurrency-stability rounds of 70 passes, passing mutation probes and zero test-quality errors/warnings. This registry reconciliation itself must now survive canonical exact-head CI before the PASS classifications are merge-authoritative.

## Post-integration reconciliation

The post-PR-#52 rebaseline inspected exact-head CI `#847` (`31983843624`) and its `v3-candidate-release-proof` artifact. That artifact collected 340 release tests, passed the reverse-order run with all 340 tests, and passed three repeated PostgreSQL/concurrency rounds of 47 tests each. The reconciliation changed a race from `TO VERIFY` only when an inspected test exercised the actual conflicting operations with deliberate overlap and asserted final state/cardinality.

At that earlier baseline R03/R05/R06 and R15 were conservatively `PARTIAL`. Phase 6K promoted R03-R08 after composing deterministic races with the complete lifecycle/recovery vertical. Phase 6F now separately promotes R12-R16 only after closing the wider worker ownership, expired-lease and crash-recovery claims. Historical evidence remains useful provenance but is no longer the current status authority.

## Phase 6F worker fencing / crash race closure

**R12 is `PASS`.** `tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r12_claim_vs_claim_has_one_current_owner` parametrizes ScheduledAction, OutboxMessage and ProviderEvent. Worker A deliberately keeps the claim transaction open; independent worker B runs the production claim surface and must skip the same locked row. After A commits, final state requires one live token and exactly one attempt increment for that ownership transition.

**R13 is `PASS`.** The same release matrix expires A, reclaims with B under a fresh token, then attempts every stale transition exposed by the family: complete, retry, dead-letter and renew, plus ProviderEvent reject. Every stale operation must fail while B remains the sole current owner. `tests/db/test_v3_worker_expired_leases.py` additionally proves that an expired token cannot finalize even before a replacement claimant exists.

**R14 is `PASS`.** Late renewal is exercised across all three families. An expired owner cannot extend itself, and after reclaim A's old token cannot extend or replace B's lease. The current token remains unchanged until B performs its own valid transition.

**R15 is `PASS`.** `tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py` enumerates both real lock orders. Cancellation-first owns the ScheduledAction row so worker claim discovery skips it; final state is `cancelled` with no token and zero attempts. Claim-first makes cancellation serialize behind the claim; after cancellation commits, the old token cannot complete and cannot pass `lock_scheduled_action_claim`, so cancelled work cannot execute a new authoritative domain consequence.

**R16 is `PASS`.** `test_worker_fencing_release_matrix.py` proves both valid Outbox completion/reclaim outcomes. Completion-first holds the row lock and a competing claim cannot acquire delivered work. Reclaim-first expires the old lease and opens the replacement claim transaction under a fresh token; while that replacement transaction remains open, stale completion must return `False`. Because the old lease is already expired, PostgreSQL may reject the stale finalizer directly on the `lease_until > clock_timestamp()` fence without waiting for the replacement row lock. The replacement token remains the only owner and is the only token that can complete the message.

Canonical CI #946 (`32063335393`) passed on exact implementation head `7f61149999ab737b3f6089b135ff1a50d1e6187f`. Artifact `v3-candidate-release-proof` `9299172598` (`sha256:bf954de52a56fc6ace13ea76de4cade8732bb4c9a267cd5900ddf21324408dd7`) is `VALID`, complete and clean-tree; it binds base `cc46234c9e3e1c3109b0aa87484d83cbefe28633`, implementation head `7f61149999ab737b3f6089b135ff1a50d1e6187f` and tested merge checkout `8e36d4e62a65df28d0ccb5d12843966da34bbf01`. It collected all 109 expected files, passed 409 tests in reverse order, passed three concurrency-stability rounds of 81 tests, killed all four mutation probes and recorded zero test-quality errors/warnings.

R20 remained `PARTIAL` at the Phase 6F boundary because Communications and ReservationAccess proved stale-worker/provider-evidence recovery but the full provider duplicate/reorder/ambiguous-outcome/reconciliation contract had not yet been closed. Phase 6G closes that wider contract below.

This registry-only R12-R16 promotion survived canonical exact-head CI before PR #60 integration. Final V3 promotion reruns the full race matrix on the eventual frozen release candidate.

## Phase 6G ProviderEvent / communications reliability race closure

**R17 is `PASS`.** `tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py` deliberately overlaps two independent tenant transactions on one provider identity. Canonically equivalent payloads converge to one ProviderEvent and replay receipt. A different payload under the same identity deterministically raises `ProviderEventDedupeConflict` and preserves the first committed fact. G13 now closes the surrounding ProviderEvent duplicate/recovery family rather than leaving this proof isolated.

**R18 is `PASS`.** `tests/integration/v3_reservation_lifecycle/test_provider_business_race.py` routes a real ProviderEvent handler into Booking's semantic attendance command while Reservation cancellation races behind the authoritative Reservation lock. Provider-command-first leaves cancellation stale on revision; cancellation-first leaves the callback command stale on revision/current lifecycle. Neither ordering permits ProviderEvent infrastructure to bypass Booking authority or retain invalid capacity.

**R20 is `PASS`.** The full external-effect uncertainty claim is now exercised as one family: send exceptions become ambiguous and schedule lookup rather than resend; lookup infrastructure failures retry lookup only; crash after prepare and crash after provider finalization before action acknowledgement both replay through provider correlation; lease loss during provider I/O fences the stale worker; repeated `ACCEPTED` reconciliation reuses one future chain; `NOT_FOUND` becomes retryable failure plus future dispatch; retryable-failure replay cannot bypass backoff; and terminal provider-result ordering is monotonic. `tests/e2e/test_communication_terminal_reconciliation_race.py` additionally runs two reconciliation actions for the same Delivery with two provider lookups already in flight, forces `FAILED(non-retryable)` to finalize first and releases `DELIVERED` second. The second finalizer must remain failed so one CommunicationTask cannot durably emit both failure and completion. Retryable failure remains recoverable from late delivered evidence because it emitted no terminal failure fact.

**R21 is `PASS`.** `tests/integration/v3_first_vertical/test_reminder_occurrence_races.py::test_r21_duplicate_reminder_materialization_serializes_to_one_occurrence_graph` holds two materializers for the same leased Reminder occurrence behind the authoritative ReminderPlan row lock and releases them together. Both calls converge to the same CommunicationTask and next occurrence. Final state requires exactly one Task, one dispatch, one next Reminder occurrence and one task-created Outbox fact; the leased ScheduledAction can be completed only once.

**R22 is `PASS`.** `tests/integration/v3_first_vertical/test_reminder_plan_races.py` deliberately overlaps ReminderPlan cancellation and materialization behind the same ReminderPlan lock and enumerates both valid winner orders. Cancellation-first makes the leased occurrence a no-op. Materialization-first may create one current task, but cancellation removes obsolete future recurrence work. With G13's full communications reliability claim now closed, no unfinished provider/reconciliation dependency remains around this race.

Canonical CI #960 (`32067492021`) passed on exact implementation head `7ca60020608c9e153dcede578767ca9969b2f98f`. Artifact `v3-candidate-release-proof` `9300680212` (`sha256:d8cfb79d89f20dfac34bca906031bba5a6650011d6911b4d66c2befeca554839`) is `VALID`, complete and clean-tree; it binds base `cf98ac7da3b171d6dd42e0f77d91787b4450cc0c`, implementation head `7ca60020608c9e153dcede578767ca9969b2f98f`, tested merge checkout `0e196a52b62e786e3d3200a9301f4be55e922f1d` and tree `d7c89c96a2e45ee4e8aaa6c4a67fa06a0edc3c92`. It collected all 115 expected files, passed 419 tests in reverse order, passed three concurrency-stability rounds of 82 tests, killed all four mutation probes and recorded zero test-quality errors/warnings.

This registry-only R17/R18/R20/R21/R22 promotion must itself survive canonical exact-head CI before PR #61 is merge-authoritative. Final V3 promotion reruns the full race matrix on the eventual frozen release candidate.

## Cross-tenant shared-capacity concurrency evidence

R25 has independent PostgreSQL connections deliberately overlapping on one hidden shared root and asserts exactly one winner plus one opaque `23P01` capacity-unavailable loser. R26 exercises Hold/Booking and SlotOffer/Booking in both ordering directions; the Booking-first SlotOffer proof requires a savepoint and asserts the opportunity closes without orphan speculative state. R27 proves rollback preserves the original Reservation and linked claim. R28 uses barriers around Resource/root authority mutation versus claim creation and validates link history. R29 combines an inverse multi-root SQL topology test with two real `RescheduleReservation` transactions synchronized immediately before the real protected shared-root lock call.

CI #847 consumed the cross-tenant inventory and repeated the concurrency selector successfully three times. At that historical baseline R25-R29 remained `PARTIAL` because this registry tracked wider release-proof closure rather than feature acceptance alone. Phase 6 G18 now closes those rows with current exact-head evidence below; the final frozen release candidate must still rerun the complete gate set.

## Phase 6 G18 adversarial race reconciliation

**R01 is `PASS`.** `tests/integration/v3_booking_commitments/test_capacity_hold_races.py::test_concurrent_conflicting_holds_commit_exactly_one_capacity_owner` uses independent PostgreSQL transactions with deliberate overlap and requires exactly one incompatible live capacity owner.

**R02 is `PASS`.** Two complementary PostgreSQL-clock proofs now cover the validity boundary. `tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_hold_confirmation_waiting_past_authoritative_expiry_is_rejected` blocks confirmation across the stored deadline and requires `CapacityHoldExpired` with no Reservation, promoted claim or residual capacity consumption. `tests/integration/v3_booking_commitments/test_g18_adversarial_race_boundaries.py::test_hold_confirmation_released_before_authoritative_expiry_consumes_hold_once` releases the same operation before the authoritative deadline and requires one consumed Hold, one Reservation and exactly one active promoted claim.

**R09 is `PASS`.** `tests/integration/v3_first_vertical/test_business_and_queue.py::test_concurrent_call_next_never_returns_same_entry` runs concurrent `CallNext` operations and requires distinct QueueEntries; the same entry cannot become current work for two callers.

**R25 is `PASS`.** `tests/db/test_v3_cross_tenant_shared_capacity.py::test_simultaneous_cross_tenant_claims_have_exactly_one_winner` deliberately overlaps two tenant commitments on one hidden shared root. Final outcomes are exactly one committed owner and one opaque generic-capacity loser; foreign tenant/root identifiers are not disclosed.

**R26 is `PASS`.** `tests/integration/v3_booking_commitments/test_g18_adversarial_race_boundaries.py::test_direct_booking_vs_foreign_capacity_hold_has_one_owner_in_both_orders` proves Booking versus foreign CapacityHold under both forced shared-root winner orders. `tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_direct_booking_vs_foreign_slot_offer_has_one_capacity_owner_in_both_orders` does the same for Booking versus foreign SlotOffer and additionally rejects false active offers, orphan Holds and orphan Claims on the losing speculative path.

**R27 is `PASS`.** `tests/integration/v3_booking_commitments/test_g18_adversarial_races.py::test_foreign_shared_booking_winning_race_rolls_back_reschedule_completely` forces the foreign shared-capacity Booking to win while a conflicting reschedule waits. The reschedule is rejected and the original Reservation location, interval, revision and active historical claim graph remain authoritative; no target claim leaks.

**R28 is `PASS`.** `tests/db/test_v3_cross_tenant_shared_capacity_authority_races.py::test_binding_activation_race_captures_live_commitment` and `::test_binding_revocation_race_preserves_historical_link` overlap binding authority changes with live claim creation and require either correct current-root backfill or preserved historical shared-root provenance without an unlinked live commitment.

**R29 is `PASS`.** `tests/db/test_v3_cross_tenant_shared_capacity_lock_topology.py::test_reversed_cross_tenant_multi_root_requests_do_not_deadlock` deliberately requests inverse multi-root orders and requires both transactions to commit under canonical root ordering rather than PostgreSQL deadlock victim selection. `tests/integration/v3_booking_commitments/test_cross_tenant_shared_capacity_reschedule_race.py::test_simultaneous_cross_tenant_reschedules_acquire_shared_roots_canonically` exercises the application reschedule path with two synchronized real transactions and validates the final active/replaced claim graph.

Canonical CI #1161 (`32240059908`) on exact PR head `90f5b9907debe281fd903b19dc9b00cbdab5accc` provides the implementation-side prerequisite for this reconciliation. Its second `PostgreSQL 18 V3 candidate proof` attempt (job `96030465480`) completed successfully after the first attempt was externally cancelled, and the same head already had successful Python quality/architecture, observability, repeated V3 bootstrap and V2 history jobs. This promotes the race registry only: G18 itself remains unclosed until the composed `.phase6/v3-adversarial-failure-proof.json` is generated by canonical CI and passes the evidence manifest's semantic validator on the wired exact head.

## Phase 6I tenant/Party-authority closure

**R23 is `PASS`.** `docs/release/v3-party-authority-adversarial-inventory.md` freezes the complete runtime Party-scoped surface and its nine distinct material exact scopes. Existing create-scope races plus the Phase 6I appointment, Queue, Waitlist, Reminder and Request management races exercise both serialized winner orders between material commands and Representation revocation with production-style application transactions. `lock_current_party_authority()` validates current exact-scope Representation, Principal and Party state inside the authoritative transaction. SlotOffer accept/decline was corrected so `waitlist.manage` authority is established after the canonical Opportunity -> Offer lock roots but before caller-selected revision, lifecycle or expiry state can be disclosed.

**R24 is `PASS`.** Direct app-role and real LOGIN tests prove fail-closed RLS, foreign-row invisibility, foreign-write rejection, `security_invoker` read isolation and forbidden role escalation. HTTP adversarial suites cover Booking, Requests, Queue, Waitlist and Reminders with foreign identifiers compared against nonexistent controls. The Reminder surface additionally proves that authenticated operator override cannot import a foreign Party; invalid recipient references are mapped to one opaque `tenant_reference_not_usable` error without echoing the probed UUID. `tests/db/test_v3_party_authority_state_adversarial.py` exercises future/expired/revoked Representation, inactive Principal/Party, wrong exact scope and same-tenant wrong Party against both read and lock authority primitives.

CI #905 (`32029659776`) on head `f6cec8e2c2b779d4b18f1a12195b52b0ffa15367` produced `evidence_status: VALID`, collected 392 tests from all 103 expected files, passed all 392 in reverse order, passed three concurrency-stability rounds of 70 tests each, passed mutation probes and included the exact real-LOGIN app function privilege inventory. Final release promotion must rerun R23/R24 on the eventual frozen release candidate; a later change to the Party-scoped capability inventory, RLS contract or app executable-function surface invalidates this PASS until re-proven.

## Test construction rules

Release race tests must use independent PostgreSQL connections or sessions and deliberate barriers so the conflicting transactions overlap. Do not replace database races with mocks, threads that never overlap database transactions, or retry loops that hide the underlying interleaving.

Each completed race proof must assert both final cardinality and final state. A test is incomplete if it only asserts that one call raised an exception.

Where two outcomes are valid, the test must enumerate both valid state machines and reject every mixed state that violates a V3 invariant.

## Lock-order review

Phase 6D/6L must additionally record lock roots and order for commands that touch the same aggregates. The deadlock suite must deliberately attempt inverse acquisition where a code path could permit it. PostgreSQL deadlock victim selection is a safety net, not the intended concurrency protocol.
