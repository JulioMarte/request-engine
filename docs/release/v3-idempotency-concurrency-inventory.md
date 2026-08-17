# V3 idempotency and optimistic-concurrency closure inventory

Status: Phase 6E executable closure completed on the current branch. G11/G12 are promoted to `PASS` in the release-gate registry subject to canonical exact-head CI on the registry reconciliation itself and mandatory rerun on the eventual frozen V3 release candidate.

## Scope rule

The idempotency release inventory contains every runtime-available HTTP command whose canonical capability is not `internal`. Operator commands are included when they are real runtime operations. Permission-only operator capabilities with `runtime_available=false` are excluded. Internal Request processing commands remain outside the public/network inventory and continue to be tested through their application contracts.

The optimistic-concurrency inventory is narrower: every runtime-available non-internal command that targets an existing caller-selected revision-managed aggregate and therefore carries `RevisionPolicy.REQUIRED`. Creation commands have no prior revision. `queue.call_next` is explicitly `SERVER_SELECTED`: PostgreSQL selects work under the queue lock and the caller does not provide a QueueEntry revision.

`tests/architecture/test_retryable_command_inventory.py` freezes both inventories against the capability registry. Adding/removing a runtime command or changing its revision policy requires updating this release contract rather than silently shrinking the Phase 6 proof surface.

## C1 — network retry / response-loss inventory

Every command below requires a stable idempotency identity and executable proof that a commit followed by loss of the HTTP response can be retried with the same normalized command and `Idempotency-Key` without a second semantic effect.

| Capability | Aggregate/effect | Revision policy | Executable response-loss evidence |
| --- | --- | --- | --- |
| `appointments.book` | create Reservation + CapacityClaim(s) | none | `test_http_idempotency_failure.py` / R19 |
| `appointments.cancel` | mutate Reservation / release claims | required | `test_http_reservation_idempotency_failure.py` |
| `appointments.reschedule` | mutate Reservation / replace claims | required | `test_http_reservation_idempotency_failure.py` |
| `appointments.confirm_attendance` | mutate Reservation attendance | required | `test_http_attendance_idempotency_failure.py` |
| `queue.join` | create QueueEntry | none | `test_http_queue_idempotency_failure.py` |
| `queue.leave` | mutate QueueEntry | required | `test_http_queue_idempotency_failure.py` |
| `queue.call_next` | server-select and mutate FIFO QueueEntry | server-selected | `test_http_queue_idempotency_failure.py` |
| `waitlist.join` | create WaitlistEntry | none | `test_http_waitlist_idempotency_failure.py` |
| `waitlist.leave` | mutate WaitlistEntry | required | `test_http_waitlist_idempotency_failure.py` |
| `waitlist.accept_offer` | mutate SlotOffer and promote Hold to Reservation | required | `v3_slot_offer_recovery/test_http_slot_offer_idempotency_failure.py` |
| `waitlist.decline_offer` | mutate SlotOffer and release Hold | required | `v3_slot_offer_recovery/test_http_slot_offer_idempotency_failure.py` |
| `reminders.create_plan` | create ReminderPlan + ScheduledAction | none | `test_http_reminder_idempotency_failure.py` |
| `reminders.cancel_plan` | mutate ReminderPlan / cancel future schedule | required | `test_http_reminder_idempotency_failure.py` |
| `requests.submit` | create Request | none | `test_http_request_idempotency_failure.py` |
| `requests.cancel` | mutate Request | required | `test_http_request_idempotency_failure.py` |

The failure transport lets the real ASGI command return from its application stack—therefore allowing the database transaction to commit—then discards the selected first response and raises a client-side `ReadError`. The retry uses the same idempotency identity and original command payload/revision. Each test asserts the authoritative cardinality/state that would reveal duplicated work: aggregate rows, revision advancement, capacity claims, scheduled work, audit/outbox consequences, or other command-specific durable state.

The same idempotency identity with a different semantic fingerprint remains a conflict and must not mutate the originally committed effect. Centralized PostgreSQL fingerprint enforcement applies to every command above. Phase 6E additionally added an attendance regression because that command historically split its capability scope by response payload and therefore could bypass the shared key/fingerprint identity.

## Attendance idempotency defect and migration 037

`appointments.confirm_attendance` exposed the most important idempotency defect found in this phase. Its HTTP/capability surface was one command, but the database identity was selected from the payload:

```text
appointments.attendance.accepted
appointments.attendance.declined
```

The fingerprint already used the semantic command `booking.record_attendance_response`, including the response value. The payload-dependent database scope meant the same `Idempotency-Key` could identify accepted and declined as two independent rows instead of producing a fingerprint conflict.

Candidate migration `037-attendance-idempotency-scope-hardening.sql`:

- aborts if historical accepted/declined/canonical rows would collide for the same Organization + Principal + key;
- normalizes historical attendance scopes to `booking.record_attendance_response`;
- retains compatibility normalization in `request_cmd.acquire_idempotency()` for legacy callers;
- keeps the response value in the fingerprint;
- causes accepted → declined reuse of one key to fail as `idempotency_conflict` without a second attendance response.

New attendance application code uses `booking.record_attendance_response` directly and no longer relies on payload-selected idempotency capability names.

## C2 — caller-selected optimistic-concurrency inventory

The following commands require real concurrent-writer proof with two independent application-runtime transactions starting from the same observed revision:

- `appointments.cancel`
- `appointments.reschedule`
- `appointments.confirm_attendance`
- `queue.leave`
- `waitlist.leave`
- `waitlist.accept_offer`
- `waitlist.decline_offer`
- `reminders.cancel_plan`
- `requests.cancel`

The authoritative aggregate roots and proof files are:

| Root | Competing public writers | Proof |
| --- | --- | --- |
| Request | cancel vs cancel | `test_http_request_booking_revision_races.py` |
| Reservation | cancel vs reschedule | `test_http_request_booking_revision_races.py` |
| Reservation | attendance accepted vs declined | `test_http_request_booking_revision_races.py` |
| QueueEntry | leave vs leave | `test_http_queue_waitlist_reminder_revision_races.py` |
| WaitlistEntry | leave vs leave | `test_http_queue_waitlist_reminder_revision_races.py` |
| SlotOffer | accept vs decline | `v3_slot_offer_recovery/test_slot_offer_runtime_revision_race.py` |
| ReminderPlan | cancel vs cancel | `test_http_queue_waitlist_reminder_revision_races.py` |

The proof may cover two commands that target the same aggregate in one race when it demonstrates the common revision root. The Reservation cancel/reschedule race therefore covers both mutation commands; the attendance race separately proves the other public Reservation writer. SlotOffer accept/decline proves both offer terminal writers.

Every proof establishes overlap deliberately at PostgreSQL, enumerates valid winner/loser outcomes, and asserts final state/cardinality. The stale writer must receive revision conflict and must not append dependent state. Merely calling the same command twice sequentially or asserting that one request raises is insufficient.

## Ordering contract and defects found

For a revision-managed retryable command the authoritative order remains:

1. acquire/serialize idempotency identity;
2. if completed, replay the stored result immediately;
3. lock the caller-selected aggregate;
4. establish Party authority when required;
5. compare `expected_revision` against the locked row;
6. validate lifecycle and dependent invariants;
7. mutate once and advance revision exactly one step;
8. append audit/outbox/dependent durable state;
9. complete the idempotency record in the same transaction;
10. commit.

Replay must precede revision/lifecycle validation. Otherwise a request that committed successfully but lost its response could be rejected on retry because its own first attempt already advanced the revision.

The Request race found a real ordering defect: terminal Request mutation previously checked `open` lifecycle before `expected_revision`. Two same-revision terminal writers could therefore serialize correctly at the row lock but the loser observed `request_not_open` rather than the required stale-revision conflict. Phase 6E normalizes Request record-result, complete and terminal mutations so revision validation precedes lifecycle after the lock; terminal mutations with a Party scope establish authority before revision as required. A command using the current revision against an already-terminal Request still receives `RequestNotOpen`; only a stale same-revision writer is classified as revision conflict.

Attendance had a second ordering issue: it checked confirmed lifecycle/revision before subject Party authority. The Phase 6E implementation now resolves subject authority after the Reservation lock, then validates expected revision, then lifecycle. This prevents lifecycle state from being consulted as the command's rejection boundary before current subject authority and makes the provider-callback-versus-business-cancellation race revision-first in either winner order.

## Evidence

Candidate CI #896 (`31999091531`) on head:

```text
c7459454a5284ab295285bd0c4f463bb239f17b0
```

produced artifact `9277905218` with digest:

```text
sha256:c2d4b3dc3bbbce05a8e08cc2935347ec9c1d6a7092006d8852496caabbfc8e91
```

and:

```text
evidence_status:        VALID
release_status:         NOT_READY   # correct; other V3 gates remain open
artifact_set_complete:  true
validation_errors:      0
expected/collected test files: 97 / 97
collected nodes:        369
reverse-order proof:    369 passed
concurrency stability:  3/3 rounds, 60 passed each
test-quality audit:     97 files / 286 tests, 0 errors / 0 warnings
```

Python quality, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and the aggregate `candidate and verticals` gate all passed. Repeated bootstrap includes migration 037.

This registry reconciliation changes only release documentation after that executable proof. Its own exact-head CI must remain green before PR integration. Final `development → main` promotion must regenerate the complete proof after the remaining V3 gates, query plans/index decisions, `0001_initial` equivalence and unified adversarial suite are frozen.

## Exit condition

G11 is closed on the current branch because all commands in C1 have executable response-loss-after-commit proof on the frozen runtime surface, the common identity/fingerprint primitive rejects semantic mismatch, and the attendance-specific scope escape was fixed and regression-tested.

G12 is closed on the current branch because every caller-selected revision-managed public aggregate represented by C2 has real concurrent application-runtime writer evidence and no stale writer can produce dependent state.

These are current-branch release-gate claims, not a declaration that V3 as a whole is ready. The final release remains `NOT_READY` until the other G01-G20 requirements are satisfied.