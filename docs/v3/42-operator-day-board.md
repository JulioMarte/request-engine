# FU-1 — Operator Day Board Contract

Status: normative for the operator day-board slice.
Owner: `booking` read composition. Extends `docs/v3/36` §0.1 criterion 4 and resolves
`docs/v3/37` R3-2 without adding mutation semantics.

## Goal

An operator can read the clinic's scheduled reservation window from one capability without
possessing per-patient representation authority. The board is an operator read, not a
subject read. It composes only authoritative existing facts and never becomes a second
source of truth.

## Public surface

`GET /v1/appointments/day-board?window_start=<offset timestamp>&window_end=<offset timestamp>&location_id=<uuid>&limit=<1..500>`
uses capability `appointments.day_board` with operator exposure. Both timestamps MUST carry
a timezone offset, the interval is half-open, and the requested window MUST be positive and
no longer than 36 hours. `location_id` is an optional exact-match filter and `limit` bounds
the row count (server default 500). A caller wanting a Dominican clinic day sends the local
`America/Santo_Domingo` day boundaries; Request Engine does not guess a clinic timezone.

Rows are ordered by reservation start then reservation UUID and include: reservation and
subject identifiers, subject display name, offering-version and location references,
reservation interval/status/revision, latest attendance response, authoritative attendance
outcome, the raw attendance timestamps (`checked_in_at`, `no_show_at`), the reported arrival
estimate, and the `effective_arrival_estimate_at` composition (the reported ETA shown only
while the reservation is `confirmed` and attendance is still `pending`), plus the
server-derived source kind.

Cancelled reservations remain visible with `status=cancelled`. Hiding them would erase
operational history from the board. Missing attendance or ETA facts remain `pending`/null;
the board never infers certainty. Contact points, identity documents, administrative
identifiers, representation internals and medical data are not exposed.

## Boundary and invariants

- The read model is `request_read.reservation_day_v1` with `security_invoker=true`; tenant
  RLS on owner tables remains authoritative.
- Booking owns reservation/attendance facts. Tenancy contributes only the Party display
  label already published by S0b; the view performs no write and no authority mutation.
- There are no locks, outbox events, scheduled actions, provider calls or idempotency keys.
- `movable` is deliberately not fabricated. A client must use the existing reschedule/
  availability surfaces to answer that policy question.
- The board may not be used by bot principals unless an operator grant is explicitly
  configured; the capability itself is operator-exposed.

## Acceptance evidence

The slice is complete only when CI proves: capability registration and window validation;
migrations apply on PostgreSQL 18; the view is tenant-isolated under the app role; a
booked-but-not-checked-in reservation appears with the Party display name; attendance and
active ETA compose without duplicate rows; cancelled reservations remain visible; and the
HTTP route rejects cross-tenant access through the normal tenant context.
