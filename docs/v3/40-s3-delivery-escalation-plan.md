# S3 Implementation Plan — Delivery Escalation (F7b)

Contract: `docs/v3/36-front-desk-operations-contract.md` (normative; §4 governs triggers,
sequential fallback, lineage and guards; §3 governs the delivery handoff/outcome loop).
Lane: `feature/s3-delivery-escalation` against `development`.
Predecessor: F7 S1/S2 merged as PR #104; S0b/S0b2 landed via `docs/v3/38`/`39` and PR #106.

## Build order

### T1 — Provider-event ingestion → fenced delivery finalize (FU-2)

- Ingestion handler that maps persisted transport outcome reports
  (`request_engine.provider_events`, claim/lease/dedupe owned by
  `platform/events/provider_events.py`) to the existing fenced delivery finalize surface.
  This is the callback half of contract §3: outcome reports arrive through the
  authenticated provider-event surface, persist-before-interpretation, deduped; replay is
  a no-op; only fenced finalize mutates delivery state.
- Register the handler for the webhook provider connection in the reference worker
  factory (`provider_event_handlers` is empty today, so `delivered` currently arrives
  only via lookup polling ~`reconcile_after_seconds`).
- Proof: a persisted outcome report finalizes the delivery in near-real-time; replayed
  report is a no-op; a late contradictory report cannot downgrade a terminal state
  (existing fenced-finalize rule, regression-proven).

### T2 — Migration `0026_f7b_delivery_escalation`

- Append-only revision (next free number after `0025_s0b2_authority_and_history`): per
  contract §11 — escalation lineage columns on communication tasks, escalation ledger
  table, `channel_policy` guard schema, voice channel vocabulary (structure only; T7).
- Tenant composite keys, FORCE RLS, identity-immutability triggers where facts are
  append-only, partial unique index enforcing at most one live task per lineage,
  DB backstop constraints for guard limits.
- `0001_initial` and the frozen V3 candidate line untouched.

### T3 — Escalation step (sequential fallback)

- Trigger evaluation per contract §4's closed trigger vocabulary; on a trigger the
  current channel attempt closes terminally and a new `CommunicationTask` is created for
  the next channel in the tenant `channel_policy` order, linked to the parent task.
- Deterministic dedupe key (parent task + channel + escalation ordinal); replay is a
  no-op. At most one live channel task per notification lineage — enforced by the
  application step and backed by the T2 partial unique index.
- Every escalation decision audited (outbox event), same lineage discipline as recovery
  actions.

### T4 — Guards and terminal facts

- `max_escalations_per_task` (default 2) and the contact fatigue guard (maximum outbound
  contacts per subject per day), per contract §4, validated as part of the
  `channel_policy` shape at plan creation and backstopped in the DB.
- Guard refusal closes the lineage with the terminal fact `fatigue_limited`; no
  remaining channels closes it with `unreachable` — both emitted as operator-visible
  outbox events, never silence.
- PostgreSQL proof: concurrent escalation attempts on the same lineage serialize to
  exactly one next-channel task (independent connections, deterministic sync; the loser
  observes the lineage already advanced or closed).

### T5 — Single delivery executor (FU-3, decision)

- **Primary decision: retire the legacy test-composed
  `CommunicationDeliveryWorker`** (`adapters/worker/delivery_worker.py`) in favor of the
  scheduled handler (`adapters/worker/scheduled_delivery.py`) as the single delivery
  executor; port the resilience tests (replay, ambiguity, poison paths) to the scheduled
  handler's surfaces.
- If porting proves disproportionate during implementation, the recorded fallback is to
  align the legacy worker's poison semantics with the scheduled handler and register the
  retirement as an explicit follow-up — the retirement decision itself does not reopen.

### T6 — Vocabulary and transport cleanup (FU-4, disposition)

- Remove `ProviderDeliveryStatus.NOT_FOUND` from the contract vocabulary
  (`modules/communications/contracts/delivery.py`) and remove the
  NOT_FOUND→FAILED+retryable mapping in fenced finalize
  (`adapters/db/delivery_store.py`): the webhook provider no longer emits it and
  contract §3 requires a not-found answer to keep the delivery ambiguous, never trigger
  a resend.
- Replace the dedupe-key-tail parsing of `attempt_no` in the webhook transport handoff
  payload (`adapters/transport/webhook_delivery_provider.py`) with an explicit
  `attempt_no` field on `ProviderSendRequest`; the handoff stops depending on string
  coupling to the dedupe key format.
- Regression: replayed handoff still never double-sends; ambiguous lookups still
  schedule reconcile, never resend.

### T7 — Voice confirmation structure (incubating, NOT implemented)

- Structure only, per the contract amendment in `36-front-desk-operations-contract.md`
  §12: the channel vocabulary admits `voice`; voice-capable `channel_policy` validation
  exists; the outcome callback contract is the provider-event surface (voice outcomes
  arrive like any other transport report).
- Non-goals, unchanged from contract §0.2/§9: no voice transport in RE, no TTS, no
  conversation state, no agent runtime. An external gateway executes calls; RE owns the
  confirmation intent and records the reported outcome through the same fenced finalize.
- No voice implementation, provider or evidence in this slice; voice is normative only
  once implemented with evidence.

### T8 — Docs + governance

- FU-5 (slot-recovery capacity boundary) — **decided:** both queue-facing compositions in
  the reference worker runtime now use `CapacitySafeSlotOfferCapacity`. The expiry handler
  already used it; the slot-recovery composition inside the reservation-lifecycle outbox
  handler was switched from the raw `PostgresSlotOfferCapacity` (which had been mirrored
  from the composition tests). Capacity loss on a queue-facing offer path is a business
  outcome (`SlotOfferCapacityUnavailable` closes the SlotOpportunity), so the safe
  boundary is used there too: it isolates the speculative Hold acquisition in a savepoint
  and normalizes any escaping shared-capacity `23P01` into the port contract, keeping a
  lost-capacity race from aborting the surrounding outbox-handler transaction with a raw
  `IntegrityError`. Both compositions (and the HTTP composition) now share one capacity
  boundary; no test composed the factory's capacity choice, so none needed changing.
- FU-6: the reference worker factory environment contract and the provider-event handler
  registration/payload contract are documented in `10-worker-runtime-hardening.md`.
- FU-7 — verified: recovery impact communications resolve recipients through the shared
  transactional channel set, and the dispatch path auto-binds only `active AND verified`
  contact points (`dispatch_resolution.py`); the recovery impact e2e
  (`tests/e2e/test_f5_recovery_delay_communication.py`, PostgreSQL) creates the durable
  impact task for a recipient whose contact point is verified, and the escalation
  step/dispatch proofs pin children to verified contact points. No behavior changed.
- `docs/README.md` map entry for this plan; doc-contract expectations updated for any
  mapped file touched.

## Review dispositions

Adversarial-review findings dispositioned after T8; all are accepted current behavior:

- A late authenticated delivered report may complete a failed-and-escalated task while its
  escalation child remains live — accepted: delivered-upgrade-not-downgrade preserves §3;
  the child's own delivery outcome reconciles independently.
- A late retryable report records evidence on the delivery row only and never resurrects a
  failed/terminal or deadline-lapsed task (CAS re-arm, delivery_store).
- Zero-reachability poison closes the lineage via the `communication.task_failed.v1` fact
  only, with no separate `lineage_unreachable` event — accepted asymmetry; the terminal
  state is operator-visible either way.
- A pre-dispatch `delivery_deadline_missed` re-attempts the SAME channel with a fresh
  workable window — pinned by test (`test_escalation_replay_and_window.py`), documented
  intent: reaching the patient after a missed deadline is the point of the trigger.

## Validation discipline

- Canonical lane for Python/architecture/unit/module work:
  `python scripts/ci/ci_jobs.py python-quality`.
- PostgreSQL 18 proofs for the escalation race and guard backstops (T4) per
  `docs/testing/README.md` and the evidence-authoring guide: falsifiable assertions,
  realistic worlds, no seeding of the result under test, independent transactions for
  concurrency claims.
- Exact-head CI on the integration lane is the merge evidence; local runs are
  development aids only.

## Explicitly deferred

- Voice execution (T7) — external gateway territory; RE records outcomes only.
- S4 inbound interpretation (identity binding + intent set) — separate slice.
- FU-1 operator day board — dedicated slice, unaffected by S3.
