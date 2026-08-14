# Request Engine V3 release race matrix

Status: Phase 6 concurrency proof inventory.

The canonical transaction and lock rules are owned by `docs/v3/02-pre-sql-contract.md`. This matrix identifies the release-level interleavings that must have deterministic PostgreSQL evidence before freeze.

Status values describe baseline proof breadth, not whether the implementation is believed correct.

| Race | Concurrent operations | Required winner/loser property | Baseline proof | Target |
|---|---|---|---|---|
| R01 | acquire capacity vs acquire same capacity | incompatible live consumption cannot both commit | PARTIAL | 6D |
| R02 | confirm Hold vs wall-clock expiry/expiry cleanup | either valid confirmation wins before expiry, or confirmation is rejected; never expired confirmation | PARTIAL | 6D/6L |
| R03 | Reservation cancel vs reschedule | one serialized lifecycle result; no leaked/replaced duplicate claims | TO VERIFY | 6D |
| R04 | SlotOffer accept vs expire | exactly one terminal offer result; no Reservation plus next-candidate offer for same capacity | PARTIAL | 6D |
| R05 | SlotOffer accept vs decline | exactly one terminal offer result and one capacity consequence | TO VERIFY | 6D |
| R06 | SlotOffer decline vs expire | exactly one release/advance consequence | TO VERIFY | 6D |
| R07 | candidate selection vs candidate selection | one active offered SlotOffer per SlotOpportunity | PARTIAL | 6D |
| R08 | Reservation cancellation vs duplicate opportunity creation | one recovery coordination chain per source identity | TO VERIFY | 6D/6E |
| R09 | CallNext vs CallNext | same QueueEntry cannot be called twice | PARTIAL | 6D |
| R10 | Request writer revision N vs writer revision N | one writer succeeds and one receives revision conflict | PARTIAL | 6E |
| R11 | Reservation/booking writer revision N vs writer revision N | one authoritative mutation succeeds; stale writer cannot overwrite | PARTIAL | 6E |
| R12 | worker claim vs worker claim | one current claim token per work item | PARTIAL | 6F |
| R13 | stale finalizer vs reclaimed worker | stale claim token cannot complete/retry/dead-letter reclaimed work | PARTIAL | 6F |
| R14 | late lease renewal vs reclaimed worker | expired owner cannot resurrect ownership | PARTIAL | 6F |
| R15 | ScheduledAction cancellation vs claim | one deterministic state transition; cancelled work cannot execute as authoritative new work | TO VERIFY | 6F/6J |
| R16 | Outbox completion vs lease reclaim | stale publisher cannot finalize another claim | PARTIAL | 6F |
| R17 | ProviderEvent duplicate ingestion vs duplicate ingestion | one provider identity; different payload under same identity is conflict | TO VERIFY | 6J |
| R18 | provider callback semantic command vs business cancellation | provider ordering cannot bypass current business authority/lifecycle | TO VERIFY | 6J/6L |
| R19 | committed command response lost vs same idempotent retry | retry returns same logical effect without duplication | MISSING | 6E |
| R20 | external side effect succeeds then worker crashes before local finalization | retry/reconciliation cannot create an uncontrolled duplicate semantic effect | PARTIAL | 6F/6J |
| R21 | reminder materialization vs same reminder materialization | occurrence identity dedupes duplicate future action creation | PARTIAL | 6J |
| R22 | ReminderPlan cancel vs occurrence materialization | obsolete future work cannot survive as valid current-plan work | TO VERIFY | 6J |
| R23 | authority/revocation change vs material command | material command revalidates authority in its authoritative transaction | PARTIAL | 6I |
| R24 | tenant A request vs guessed tenant B aggregate ID | no cross-tenant read/write or existence oracle through protected surfaces | PARTIAL | 6I |

## Current Phase 6I tenant evidence

R23 now has two independent evidence layers. `tests/db/test_v3_tenant_isolation_adversarial.py` proves both winner orders between Representation revocation and `lock_current_party_authority()` with independent PostgreSQL connections. `tests/integration/v3_first_vertical/test_http_request_authority_race.py` then proves a material Request submission already holding Representation authority cannot have that authority revoked before its transaction commits; after revocation commits, the same represented actor is rejected with `party_authority_required`. R23 remains `PARTIAL` until the remaining subject-scoped material mutation families receive equivalent deterministic barriers.

R24 now has direct app-role and HTTP evidence. The DB suite proves fail-closed RLS behavior, foreign-row invisibility, foreign-write rejection, `security_invoker` read isolation, and foreign-versus-nonexistent authority lookups. HTTP adversarial suites exercise Booking, Requests, Queue, and Waitlist using valid Tenant B identifiers from Tenant A and compare them with nonexistent controls. The tests also assert final Tenant B state and absence of cross-tenant rows. R24 remains `PARTIAL` until the application vertical runs through a real least-privileged production login and the remaining protected worker/admin/function surfaces are exhaustively classified and attacked.

## Test construction rules

Release race tests must use independent PostgreSQL connections or sessions and deliberate barriers so the conflicting transactions overlap. Do not replace database races with mocks, threads that never overlap database transactions, or retry loops that hide the underlying interleaving.

Each completed race proof must assert both final cardinality and final state. A test is incomplete if it only asserts that one call raised an exception.

Where two outcomes are valid, the test must enumerate both valid state machines and reject every mixed state that violates a V3 invariant.

## Lock-order review

Phase 6D/6L must additionally record lock roots and order for commands that touch the same aggregates. The deadlock suite must deliberately attempt inverse acquisition where a code path could permit it. PostgreSQL deadlock victim selection is a safety net, not the intended concurrency protocol.
