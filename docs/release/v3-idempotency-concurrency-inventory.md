# V3 idempotency and optimistic-concurrency closure inventory

Status: Phase 6E working inventory. This document freezes the command families that must be proven before G11/G12 may move from `PARTIAL` to `PASS`.

## Scope rule

The idempotency release inventory contains every runtime-available HTTP command whose canonical capability is not `internal`. Operator commands are included when they are real runtime operations. Permission-only operator capabilities with `runtime_available=false` are excluded. Internal Request processing commands remain outside the public/network inventory and continue to be tested through their application contracts.

The optimistic-concurrency inventory is narrower: every runtime-available non-internal command that targets an existing caller-selected revision-managed aggregate and therefore carries `RevisionPolicy.REQUIRED`. Creation commands have no prior revision. `queue.call_next` is explicitly `SERVER_SELECTED`: PostgreSQL selects work under the queue lock and the caller does not provide a QueueEntry revision.

## C1 — network retry / response-loss inventory

Every command below requires a stable idempotency identity and must prove that a commit followed by loss of the HTTP response can be retried with the same normalized command and `Idempotency-Key` without a second semantic effect.

| Capability | Aggregate/effect | Revision policy |
| --- | --- | --- |
| `appointments.book` | create Reservation + CapacityClaim(s) | none |
| `appointments.cancel` | mutate Reservation / release claims | required |
| `appointments.reschedule` | mutate Reservation / replace claims | required |
| `appointments.confirm_attendance` | mutate Reservation attendance | required |
| `queue.join` | create QueueEntry | none |
| `queue.leave` | mutate QueueEntry | required |
| `queue.call_next` | server-select and mutate FIFO QueueEntry | server-selected |
| `waitlist.join` | create WaitlistEntry | none |
| `waitlist.leave` | mutate WaitlistEntry | required |
| `waitlist.accept_offer` | mutate SlotOffer and promote Hold to Reservation | required |
| `waitlist.decline_offer` | mutate SlotOffer and release Hold | required |
| `reminders.create_plan` | create ReminderPlan + ScheduledAction | none |
| `reminders.cancel_plan` | mutate ReminderPlan / cancel future schedule | required |
| `requests.submit` | create Request | none |
| `requests.cancel` | mutate Request | required |

For each command the proof must assert more than an HTTP replay. It must check the authoritative cardinality/state that would reveal duplicated work: aggregate rows, revision advancement, capacity claims, scheduled work, audit/outbox consequences, or other command-specific durable state.

The same idempotency key with a different semantic fingerprint remains a conflict and must not mutate the originally committed effect.

## C2 — caller-selected optimistic-concurrency inventory

The following commands must have a real concurrent-writer proof with two independent application-runtime transactions starting from the same observed revision:

- `appointments.cancel`
- `appointments.reschedule`
- `appointments.confirm_attendance`
- `queue.leave`
- `waitlist.leave`
- `waitlist.accept_offer`
- `waitlist.decline_offer`
- `reminders.cancel_plan`
- `requests.cancel`

The release proof may cover two commands that target the same aggregate in one race (for example Reservation cancel versus reschedule, or SlotOffer accept versus decline) when it demonstrates the common revision root. Every mutable public aggregate still needs at least one real two-writer proof using the production application role and final-state assertions.

A valid race proof must establish overlap deterministically, enumerate valid winner/loser outcomes, and prove that the loser produces no dependent side effect. Merely calling the same command twice sequentially or asserting that one request raises is not sufficient.

## Ordering contract

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

## Exit condition

G11 may move to `PASS` only when all commands in C1 have executable response-loss-after-commit proof on the frozen runtime surface, including different-payload reuse protection, and the final exact-head evidence bundle is valid.

G12 may move to `PASS` only when every caller-selected revision-managed aggregate represented by C2 has real concurrent application-runtime writer evidence and no stale writer can produce dependent state.

This inventory is intentionally closed by an architecture test. Adding/removing a runtime command or changing its revision policy must update this release contract rather than silently changing what Phase 6 claims to prove.
