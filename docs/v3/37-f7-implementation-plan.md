# F7 Implementation Plan

Status: working plan for `feature/f7-front-desk-operations`, subordinate to
`36-front-desk-operations-contract.md` (the contract is authoritative; this file tracks
slices, files, evidence and order).

## Slice order and dependencies

```text
S1 F7a remote delivery transport      (communications; no schema change)
S2 F7d reservation arrival estimates  (booking; migration 0022)
S3 F7b delivery escalation policy     (communications; depends on S1 states)
S4 F7c inbound interpretation         (depends on S1/S2; identity binding first)
S5 F7e same-day selection subset      (queue; own PostgreSQL proof lane)
S6 F7f after-hours intake             (application composition; last)
```

S1 and S2 are independent (disjoint modules) and can proceed in parallel.

---

## S1 — F7a Remote delivery transport

**Problem:** `CommunicationDeliveryProvider` is interface-only; no production transport
exists, so no reminder/confirmation ever sends.

**Deliverable:** a webhook-based remote transport provider implementing the existing
protocol, plus composition wiring. No schema change, no new HTTP capability.

**Files (expected):**
- `src/request_engine/modules/communications/adapters/transport/webhook_delivery_provider.py`
  — implements `send` / `lookup` against a configured HTTPS webhook.
- composition/worker wiring: register the provider under a provider key
  (e.g. `webhook`) when a webhook base URL is configured.
- unit tests with a fake HTTP transport (no real network in tests).

**Semantics (from contract §3):** deterministic delivery identity; transport dedupes;
2xx = accepted handoff; non-2xx = retryable failure; transport exception = AMBIGUOUS then
reconcile via `lookup`; `lookup` maps to delivered/failed/unknown only.

**Acceptance criteria:**
1. `send` builds the handoff payload with task id, dedupe key, attempt number, channel,
   recipient contact point, content reference, `expires_at`, `reconcile_after_seconds`.
2. Non-2xx response -> retryable failure path (existing retry semantics, new attempt
   scheduled, not terminal).
3. Transport exception -> AMBIGUOUS; a reconcile is scheduled; no resend occurs.
4. `lookup` never invents delivered/failed from `unknown`.
5. Provider absent/unconfigured -> existing `provider_not_configured` failure path is
   unchanged (regression).
6. Ruff + Pyright clean; unit tests pass.

**Explicitly out of scope for S1:** callback ingestion changes (existing provider-event
surface is reused as-is), escalation (S3), real HTTP integration tests.

---

## S2 — F7d Reservation arrival estimates

**Problem:** "voy 20 min tarde" has no home. The receptionist arbitrates late arrivals from
memory; F4 projection and the operator board cannot see them.

**Deliverable:** durable arrival-estimate fact on reservations + public command + route.

**Files (expected):**
- `migrations/versions/0022_f7_reservation_arrival_estimates.py` — new table
  `request_engine.reservation_arrival_estimates`: tenant composite keys, reservation FK,
  `estimated_arrival_at` (timestamptz), `source_kind` CHECK (`customer`|`operator`),
  `asserted_by_principal_id`, `asserted_at`, `superseded_at`; at most one active row per
  reservation (partial unique index `WHERE superseded_at IS NULL`); FORCE RLS; identity
  immutability + supersede coherence triggers; claim must reference a `confirmed`
  reservation (DB backstop).
- booking domain: arrival-estimate value/fact types.
- application command `record_arrival_estimate` (idempotent, `expected_revision` fenced,
  subject/override authority resolved in-transaction, audit + outbox event
  `reservation.arrival_estimate_recorded.v1`).
- HTTP route: public capability `appointments.record_arrival_estimate`
  (`POST /v1/appointments/{reservation_id}/arrival-estimate`), registered in the booking
  capability registry.
- read surface: active estimate included in reservation read view (advisory field).
- unit tests: authority, idempotency, revision fencing, supersede behavior, reject on
  non-confirmed reservation.
- PostgreSQL proof (S2-GATE, may be a follow-up lane): concurrent estimates -> exactly one
  active row; append-only history; RLS isolation.

**Acceptance criteria:**
1. Recording on a confirmed reservation creates an active estimate and supersedes any
   previous one without rewriting history.
2. Rejected on cancelled/missing reservation (DB backstop included).
3. Wrong `expected_revision` / wrong authority / replayed key behave exactly like the
   other guarded booking commands.
4. Degenerate behavior: reservations without estimates are unchanged everywhere
   (regression).
5. Ruff + Pyright clean; unit tests pass; migration applies cleanly.

---

## S3 — F7b Delivery escalation policy (after S1)

**Problem:** definitive channel failure is terminal; unreachable patients are silent.

**Deliverable:** closed-trigger escalation with sequential channel fallback, lineage and
guards (contract §4).

**Files (expected):** communications escalation handler in the delivery worker path;
policy schema for guards (tenant `channel_policy` extension); unit tests; PostgreSQL
concurrency proof for the escalation step.

**Acceptance criteria (from contract §10):** deterministic dedupe (replay no-op); never
two live channel tasks per lineage; fatigue guard -> visible `fatigue_limited` terminal;
exhausted channels -> visible `unreachable`; escalation decisions audited.

---

## S4 — F7c Inbound interpretation boundary (after S1+S2)

**Deliverable:** identity binding (verified contact point -> party, representations for
acting-for), closed intent set v1 (contract §5) lowering to existing owner commands,
human-review demand surface for ambiguity, replay/contradiction semantics.

**Acceptance criteria (from contract §10):** unbound sender -> review demand with zero
mutation; each intent lowers with in-transaction authority; replayed message no-op.

---

## S5 — F7e Same-day selection subset (own proof lane)

**Deliverable:** `operator_select`, `recall_hold`, `skip` per contract §7, plus projection
honesty under holds and the degenerate-equivalence proof.

**Gate:** this slice touches the most invariant-sensitive transaction in the repo
(`call_next`). It requires its own PostgreSQL proof lane before merge and must not be
bundled with other slices.

---

## S6 — F7f After-hours intake (composition)

**Deliverable:** request definition guidance + application-layer conversion flow using
only existing owner commands. No tables, no new capabilities.

---

## Validation discipline

- Every slice runs the repository canonical lane that owns its proof:
  `python scripts/ci/ci_jobs.py python-quality` minimum; PostgreSQL proofs for schema /
  concurrency claims per `docs/testing/README.md`.
- Exact-head CI on the integration lane is the merge evidence; local runs are development
  aids only.
- Evidence follows `docs/testing/evidence-authoring-guide.md`: falsifiable assertions,
  realistic worlds, no seeding of the result under test.
