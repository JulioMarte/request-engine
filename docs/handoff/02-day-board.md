# Handoff 02 — Operator Day Board (FU-1)

Audience: the next engineer/agent with zero context. Read `AGENTS.md`, `docs/v3/36`
(§0.1, §7) and `docs/v3/37` (round-3 audit) before coding. This file is a handoff map,
not a normative contract; the contract of record for F7 is `docs/v3/36`.

## 1. The problem

`docs/v3/37` R3-2: **booked-but-not-checked-in patients are invisible to every read
surface.** Patient names, attendance state and arrival estimates never reach any board.
Verified in code: the only reservation read is `GET /v1/appointments/{reservation_id}`
(`src/request_engine/modules/booking/api/router.py:120-135`), one reservation at a time,
and `get_reservation_status`
(`src/request_engine/modules/booking/application/queries/get_reservation_status.py:18-43`)
is gated by subject authority — an operator principal without a representation grant on
that specific patient cannot even read it. There is no capability anywhere in the repo
that lists reservations for a day.

This is goal criterion 4 of `docs/v3/36` §0.1 ("She can answer *who is coming, who
confirmed, who is late, who can move* from one surface") failing **structurally**: it is
not missing polish, there is no surface to polish. Today the secretary must poll
reservation-by-reservation, which in practice means the paper book and WhatsApp stay
authoritative (criterion 5, the week-3 test).

## 2. What exists to build on (all verified in code)

An implementation would compose these; none of them needs new mutation semantics:

| Fact | Where it lives |
|---|---|
| Reservation status (`confirmed`/`cancelled`), interval `during`, revision | `request_engine.reservations`; contract `Reservation` in `src/request_engine/modules/booking/contracts/appointments.py` |
| Attendance response (`pending`/`accepted`/`declined`) | `request_engine.attendance_responses`; contract `AttendanceStatus` in the same file; command `booking/application/commands/record_attendance.py` |
| Attendance outcome (`checked_in`, `no_show`) | `AttendanceOutcomeStatus` in `booking/contracts/attendance.py`; commands `check_in_reservation.py`, `evaluate_no_show.py`, worker `booking/adapters/worker/no_show.py` |
| Arrival estimates (F7d, implemented) | `request_engine.reservation_arrival_estimates` (migration `0022_f7_reservation_arrival_estimates.py`); command `record_arrival_estimate`; route `POST /v1/appointments/{id}/arrival-estimate`; `source_kind` ∈ `customer|operator` in `booking/contracts/arrival_estimates.py` |
| Composed single-reservation read view | `request_read.reservation_status_v1` (migration 0022, `security_invoker` view joining attendance + active estimate). Composition is proven at SQL level — a day view can follow this exact pattern |
| Patient display name | `request_engine.parties.display_name`; cross-module contract `RegisteredParty` in `src/request_engine/modules/tenancy/contracts/party_registry.py`. The S0b party registry API (routes in `tenancy/api/party_registry_routes.py`, migrations 0023–0025) is what creates these parties |
| Queue entries (`waiting`/`called`/`serving`/…) | `QueueEntryStatus` in `queue/contracts/service_queue.py`; views `request_read.service_queue_status_v2` (migration 0005) |
| Name-join precedent for a staff board | `request_read.live_service_staff_v1` (migration 0005) already joins `parties.display_name` into a staff-facing read for the walk-in live queue, exposed via `queue.staff_read` (`queue/api/live_read_router.py`). This is the closest existing analogue to the day board — but it covers the live queue, not scheduled reservations |
| Reminders / delivery truth | `ReminderPlan` (`communications/contracts/reminders.py`), `reminder_plans`; delivery state in `communication_deliveries` (contract §9: no second delivery truth) |

The honest gap statement: **every ingredient above is per-object.** Nothing composes them
across a day. The board is a new read capability, not a new truth domain. Note also what
does NOT exist and must not be improvised:

- No offering/resource display names join exists for reservations (only for live-queue
  rows and copilot queries); the board must decide which catalog labels it shows.
- No delivery/reminder state joins reservations; "was the reminder sent?" is answerable
  today only per-`CommunicationTask`, and per doc 36 §9 there is exactly one delivery
  truth (`communication_deliveries`) — the board may read it but never restate it.
- `live_capacity` (F4) is an advisory projection module and is explicitly not a shortcut
  into booking/queue persistence (`src/request_engine/modules/AGENTS.md`); do not hang
  the board off it.

## 3. Connection-surface gate — answer BEFORE coding

Copy of the `AGENTS.md` gate, pre-filled where the repo already decides:

```text
Business owner:              booking (reservation facts + attendance). Open decision:
                             read-only composition could also live in a documented read
                             surface; default to booking-owned.
Capability:                  one read-only Query (no Command, no mutation) — day board.
Inbound caller and contract: receptionist HTTP client; one GET returning the composed
                             day view; stable capability string (single, closed).
Authentication/authorization: operator capability gate (NOT subject authority per row —
                             that gate is what makes per-reservation reads unusable for
                             the board). Capability decides; do not leak other tenants.
Application Command/Query:   one Query type; no generic "list reservations" API beyond
                             the board's needs.
Transaction and idempotency: read-only; no locks beyond tenant RLS context (precedent:
                             `PostgresLiveQueueReader.staff_queue`).
Domain invariants:           none mutated; honest-unknown rule (F4/F7d): no estimate ->
                             unknown, never invented; no certainty fabrication.
Database surface:            new `request_read.*` view (security_invoker) composing
                             reservations + attendance + active estimate + parties, or
                             per-module contract readers. Never write-surface SQL.
Cross-module contract surface: tenancy party display names via `tenancy.contracts`;
                             names cross the boundary as contract dataclasses, not raw
                             rows (see live_service_staff_v1 for the SQL precedent).
Provider/event/scheduled surface: none. No reminders, no outbox, no network I/O.
Failure/retry/reconciliation: read fails open as HTTP error; no partial-truth board rows.
```

What crosses the boundary: reservation id, interval, status, attendance response/outcome,
active arrival estimate + `source_kind`, party display name, offering/resource/location
references. What must NOT cross: authority internals, contact points, capacity truth,
anything PII beyond the display name (mirror S0b's PII-minimal stance).

## 4. Suggested build order

1. **Read-only day-board Query first.** New `request_read.reservation_day_v1`-style view
   (new append-only Alembic revision; next number after 0026) + booking application query
   + route in a NEW file following the `arrival_estimate_routes.py` pattern. Sketch of
   the read shape (illustrative, not normative):
   - rows keyed by reservation id for a tenant + day window;
   - columns: interval, status, attendance response/outcome timestamps, active estimate
     (+ `source_kind`), subject display name, offering/resource/location references;
   - the view must be `security_invoker` so tenant RLS of the underlying tables applies
     (the pattern every existing `request_read.*` view follows).
2. PostgreSQL proofs for the view composition: attendance/estimate join correctness,
   RLS/tenant isolation under the runtime role, security_invoker behavior.
3. e2e HTTP proof: capability gate, tenant isolation probe (precedent: the S2 e2e
   tenant-isolation probe registered in doc 37), day-window filtering.
4. Operator actions (e.g. check-in from the board) come later as ordinary owner
   commands reusing existing endpoints — do not bundle mutations into the read slice.
   `appointments.confirm_attendance`, `appointments.cancel`,
   `appointments.record_arrival_estimate` and reschedule all already exist; the board's
   "movable" question is answered by running reschedule, not by a new API.

**Traps:**
- **Line budget**: files are capped at 120 effective lines and ratcheted files may not
  grow. `booking/api/router.py` is already far above the cap — you may NOT add the board
  route there. New files only (`check_python_file_budget.py` will fail otherwise).
- **Doc contract**: `scripts/ci/check_documentation_contract.py --base origin/development`
  gates contract-sensitive code changes on normative docs. A new read capability likely
  touches `docs/v3/36` (new slice/acceptance) — update the contract in the same change,
  and note `docs/handoff/00` and `01` are owned by another agent.
- Architecture tests forbid cross-module imports outside `contracts`; the board must not
  import booking internals from another module, and `live_capacity` must not become a
  shortcut into booking persistence.
- Migration discipline: append-only revision, tenant composite keys, FORCE RLS for any
  new table; views use `security_invoker`.

## 5. Open owner decisions (ask before starting)

1. Which columns the board shows, and whether attendance outcome (`checked_in`/
   `no_show`) appears next to attendance response (`accepted`/`declined`) or collapsed.
2. Timezone handling: the clinic is in the DR (single zone in practice) but the DB stores
   timestamptz — does the board take a local clinic day boundary or a UTC window?
3. Which statuses appear (cancelled reservations: hide, or show struck through?).
4. Pagination/windowing: one clinic day is small, but is the board per-location,
   per-resource, or per-organization?
5. Display-name exposure policy for the HTTP surface (PII-minimal like S0b, or full).
6. Capability string and which principal kinds get it (bot principals should not;
   precedent: `queue.staff_read` is capability-gated per route, and S0b bot principals
   get only a closed creation/lookup subset).
7. Whether "movable" is computed here (advisory) or deferred to live_capacity/F4.
8. Ordering on the board: interval time is the obvious default; anything else must stay
   derived at read time (never a stored position — same discipline as queue order).

## 6. What this handoff could NOT verify

Stated explicitly so you do not trust it blindly:

- Whether an Alembic revision `0027` is truly free at the time you start — this handoff
  saw head `0026_s3_escalation_lineage.py`; re-check `migrations/versions/`.
- Whether the PostgreSQL runners' exact invocation names changed; this handoff only
  confirmed what `docs/testing/README.md` says (`scripts/ci/run_current_product.sh` owns
  current-product + e2e evidence). No PostgreSQL runner was executed while writing this.
- The exact effective-line count of `booking/api/router.py` (the budget checker owns it);
  only that it is far above the 120 cap and therefore ratcheted.
- Nothing in this document was exercised against a running PostgreSQL instance; every
  claim above is from reading code, migrations and contracts at commit `063332fc`.
