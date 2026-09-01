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
- PostgreSQL proofs (landed with S2): sequential supersede/immutability/backstop suite,
  plus the concurrent proofs required by contract §10 — two concurrent command recordings
  serialize on the reservation lock (exactly one active estimate, append-only history) and
  a direct concurrent insert is rejected by the partial unique index (23505,
  `reservation_arrival_estimates_one_active_uq`).

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

## Round-3 usability audit (post-4554282f) — priority reordering

An adversarial usability walkthrough (setup journey, day-of journey, patient/bot journey,
public API only) found that the transactional core is operable but the product has no front
door. Registered as authoritative for slice ordering:

- **R3-1 Party registry (root blocker):** there is no API to create parties (patients or
  authority parties), contact points, or representations — ~9 of ~16 prerequisite objects
  are SQL/deployment-only. Booking, queue, waitlist, reminders and every
  `/v1/operations/*` configuration endpoint demand objects no API can produce. Also no
  party lookup by name/phone. → **New slice S0b (before S3).**
- **R3-2 Unified day agenda read:** booked-but-not-checked-in patients are invisible to
  every read surface; patient names, attendance state and arrival estimates never reach
  any board. Goal criterion 4 fails structurally. → **Elevated: part of S0b/S5 lane.**
- **R3-3 Triage grammar (F7e subset) is the load-bearing day-of slice:** urgent
  selection, squeeze-in and stepped-out have zero truthful representation; every workaround
  fabricates durable lies. The §7 semantic contract (`operator_select`, `recall_hold`,
  `skip`) plus the day board is the secretary's core ask. → unchanged TARGET, now
  explicitly the highest-value unimplemented slice.
- **R3-4 Bot-as-subject authority mode:** subject authority is
  representation-or-override only; representations are unprovisionable; a bot using
  operator override durably misattributes patient facts (`source_kind=operator` for the
  patient's own ETA). Verified-contact-point binding as a first subject-authority source,
  plus a delivery-handoff correlation block (subject/purpose/conversation key), is the
  prerequisite for F7c inbound to be attributable. → folded into S4's contract.
- **R3-5 Operator day-of controls are incident-gated:** "we are 30 min late", "stop
  intake", "extend day" require an auto-generated incident no operator surface can create;
  notify-impact is one recipient per call. → new slice item (S3-adjacent, Queue/Recovery
  composition).

Reordered build order: **S0b (party registry + lookup + contact-point verification) →
S3 (escalation) → day board (FU-1, full scope incl. attendance + estimates) → S5 (triage
subset) → S4 (inbound, with R3-4 identity mode) → S6.**

## Validation discipline

- Every slice runs the repository canonical lane that owns its proof:
  `python scripts/ci/ci_jobs.py python-quality` minimum; PostgreSQL proofs for schema /
  concurrency claims per `docs/testing/README.md`.
- Exact-head CI on the integration lane is the merge evidence; local runs are development
  aids only.
- Evidence follows `docs/testing/evidence-authoring-guide.md`: falsifiable assertions,
  realistic worlds, no seeding of the result under test.

## Registered follow-ups (from PR #104 adversarial reviews, rounds 1-2)

Each item below is owned and sequenced; none may be silently dropped. Round-2 fixes already
landed on this branch: bounded reconcile (deadline gate + durable `delivery_deadline_exceeded`),
`DeliveryConfigurationError` -> durable poison path, channel-policy shape validation at plan
creation (422), redirect refusal in the webhook transport, server-derived `source_kind`,
ETA closed validation rules, single capability string, e2e tenant-isolation probe for the new
operation, reservation-lifecycle wiring in the reference worker factory (slot recovery +
booking-native notifications now run in the documented deployment), optional `provider_key`
with sole-provider dispatch binding (slot-offer and recovery notifications now dispatchable),
and the publisher-factory isinstance guard.

| # | Item | Why it matters to the product goal | Lands with |
|---|---|---|---|
| FU-1 | Operator day board: who is coming / confirmed / late / movable — for reservations AND attendance state (not only the estimate) | Goal criterion 4 is NOT-MET: no day view exists at any layer today; the secretary polls reservation-by-reservation | Dedicated slice (highest priority after S4) |
| FU-2 | Provider-event ingestion handler mapping transport outcome reports to fenced delivery finalize (callback half of contract §3; today `delivered` arrives only via lookup polling ~`reconcile_after_seconds`) | Closes the delivered-state loop in near-real-time; required before S3 escalation trusts outcomes | S3 (prerequisite) |
| FU-3 | Decide the legacy `CommunicationDeliveryWorker` (test-composed) vs the scheduled handler: it does not poison on `DeliveryConfigurationError` | Divergent failure semantics between two delivery executors invites silent-stuck regressions in test compositions | S3 |
| FU-4 | `ProviderDeliveryStatus.NOT_FOUND` remains armed in finalize (FAILED + retryable -> resend) though the webhook provider no longer emits it; also `attempt_no` is derived by parsing the dedupe-key tail | Armed-but-unreachable resend vocabulary and string coupling; both need an explicit disposition | S3 |
| FU-5 | Consider `CapacitySafeSlotOfferCapacity` boundary in the reference-factory slot-recovery composition (raw adapter mirrored from the composition tests) | Consistency with the safe-capacity boundary used by the expiry handler in the same runtime | S3 |
| FU-6 | Reference worker factory env contract (`REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY`, `REQUEST_ENGINE_WORKER_PRINCIPAL_ID`) documentation in `docs/v3/10-worker-runtime-hardening.md` | Deployment-facing configuration contract belongs in the canonical hardening doc | docs change with S3 |
| FU-7 | Recovery impact-communication policy: recovery tasks now use the shared transactional channel set + dispatch-time provider binding; confirm recipients resolve verified contact points as intended | Recovery communications are the F5 surface most exposed to the new fail-fast semantics | verify with S3 |

## Composition contract for the webhook transport (S1)

The reference worker factory `bootstrap/reference_worker_factory.py` is the documented
composition path a deployment may name via `REQUEST_ENGINE_WORKER_FACTORY`. Configuration
is explicit and fails loud at startup: `REQUEST_ENGINE_WEBHOOK_BASE_URL` (required),
`REQUEST_ENGINE_WEBHOOK_AUTH_HEADER` (optional, `Header-Name: value`), plus the existing
worker runtime variables. Tenants select the transport per channel via
`channel_policy.provider_key = "webhook"`. Provider selection remains a deployment concern;
no adapter is ever inferred.
