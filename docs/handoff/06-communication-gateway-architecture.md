# Handoff 06 — Communication Gateway Architecture (accepted direction)

Status: accepted product/architecture direction (owner decision, 2026-09-01). Not yet
implemented. Audience: the next engineer/agent AND the repo owner (Julio), who is not a
professional engineer.

Companion documents: `docs/handoff/00..05` (owned separately) and
`docs/handoff/07-open-decisions-and-debt.md` (the honest backlog).

## 1. The problem in plain language

Request Engine (RE) is the clinic's system of record: appointments, queues, parties,
notifications, escalations. Real patients talk over WhatsApp (later, voice). Provider
SDKs (Meta's WhatsApp Cloud API, Chatwoot, voice platforms) are chatty, non-deterministic
and change often. RE must never couple its transactional database authority to that
chattiness. So we place ONE thin external service between RE and the providers.

## 2. The three layers

```text
Layer 1: REQUEST ENGINE          Layer 2: COMMUNICATION GATEWAY       Layer 3: PROVIDERS
truth + policy + authority  -->  renders + executes + reports  -->  WhatsApp Cloud API,
decides what/whom/channel/        consumes RE's outbox events,          SMS gateway,
when-to-escalate                  executes via provider SDKs,           voice platform (later)
never touches provider SDKs       reports durable outcomes back
```

**Layer 1 — Request Engine.** Owns all authority: which message, to whom, on which
channel, when to escalate to the next channel (the S3 escalation ladder,
`docs/v3/36` §4 / `docs/v3/40`). It composes durable intents (outbox events,
`CommunicationTask` rows) and records outcomes. It never imports a provider SDK.

**Layer 2 — Communication Gateway.** ONE deployment-owned service. It:
- consumes RE's outbox events (the delivery handoff), including the template key and
  render context RE already puts in the payload (`webhook_delivery_provider.py:111-115`);
- renders the final message content from that context (RE sends intent, not prose);
- executes sends through channel provider SDKs — Chatwoot for text conversations, a
  voice platform later;
- calls RE back with outcome reports through RE's authenticated provider-event surface.
  An LLM conversation agent may live INSIDE the gateway. It must NEVER live inside RE.

**Layer 3 — Providers.** WhatsApp Cloud API, an SMS gateway, a voice platform. Dumb
pipes plus their own delivery receipts.

## 3. Why the LLM lives in the gateway, not in RE

Latency, cost and non-determinism. RE's authority is transactional PostgreSQL semantics:
one command, one transaction, durable facts. An LLM call takes seconds, costs money per
token, and can answer differently every time. Those properties are incompatible with
authoritative state changes; they are fine for holding a conversation. The gateway turns
free conversation into typed, authenticated, idempotent semantic calls against RE; RE
stays deterministic (see `docs/v3/38` §5 for how a bot principal authenticates and how
little authority it gets).

## 4. The two integration seams — both already exist in RE (verified)

**OUT (RE → gateway): the outbox.**
- Durable facts are appended inside the same transaction that changes business state
  (`append_outbox`, e.g. `escalation_triggers.py:74-81`).
- The worker drains them: `src/request_engine/bootstrap/worker.py` assembles the
  runtimes; `src/request_engine/bootstrap/reference_worker_factory.py` is the
  `REQUEST_ENGINE_WORKER_FACTORY` target. Its environment contract (all required, fails
  loudly at startup) is specified in `docs/v3/10-worker-runtime-hardening.md`
  ("Reference worker factory environment contract", lines 225-234).
- The publisher is a deployment concern: `OutboxPublisher` is only a Protocol
  (`entrypoints/worker/outbox_runtime.py:45`); there is NO concrete production publisher
  in the repo. `REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY` must name one, or startup fails.
  The delivery transport RE already ships is the HTTPS webhook provider
  (`modules/communications/adapters/transport/webhook_delivery_provider.py`), which is
  the natural contract shape for the gateway's consumer endpoint.

**IN (gateway → RE): provider events.**
- Callbacks are persisted BEFORE interpretation (`docs/v3/10` "ProviderEvent"; dedupe
  identity `organization + provider_key + connection_key + provider_event_id`).
- The reference registration is exactly one handler under `(provider_key="webhook",
  connection_key="primary")` (`bootstrap/communication_providers.py:38-52`).
- The outcome-report payload contract is in `docs/v3/10` lines 144-152: `dedupe_key`
  (required; the delivery is resolved from the authenticated lease, never from a
  client-sent id), `status` in {`accepted`, `delivered`, `failed`}, plus optional
  `retryable`, `provider_message_id`, `result_data`.
- Finalize is fenced and terminal-monotone: a late contradictory report cannot downgrade
  a delivered state, a report about an unknown identity is a durable no-op, a malformed
  report becomes a rejected durable fact — proven in
  `tests/integration/v3_worker_runtime/test_delivery_outcome_events.py` and
  `test_delivery_outcome_event_fencing.py`, and codified as guarantee
  `INV-DELIVERY-OUTCOME-001` in `docs/testing/current-guarantees.toml:234-238`.
- Reconciliation backstop: RE also runs a scheduled `communications/reconcile_delivery`
  action (registry in `docs/v3/10` lines 180-187) and the webhook provider has a
  `lookup` status endpoint (`webhook_delivery_provider.py:78-90`), so RE does not depend
  solely on the gateway calling back.

## 5. Gateway responsibility boundaries

The gateway must NEVER:
- decide channels, timing or escalation — that is RE's S3-owned policy;
- invent content — it renders from RE's template key + context, nothing more;
- own delivery state — RE's delivery rows are the only delivery truth; the gateway may
  cache nothing that RE would then trust;
- retry ambiguously — if it cannot tell whether WhatsApp got the message, it reports the
  ambiguity (or lets RE's reconcile polling resolve it); reconciliation-first is RE's
  discipline (`docs/v3/10` crash-recovery and outbox-pipeline sections).

The gateway MUST:
- authenticate to RE for callbacks (the deployment's callback adapter owns credential
  validation; RE trusts nothing else — `docs/v3/10` "Manual replay" section applies the
  same trust model);
- be idempotent under replay: RE re-delivers events after lease loss by design
  ("Re-execution is expected", `docs/v3/10` line 80);
- report outcomes durably, matching the payload contract in §4-IN.

## 6. Build order for the gateway (each step done = durable facts flow both ways)

1. **Outbox consumer.** An HTTPS endpoint (or queue consumer fed by a thin deployment
   publisher) that accepts RE's handoff payload and persists it durably before acting.
   Done when: replaying the same outbox event twice causes no duplicate provider send.
2. **WhatsApp delivery adapter.** Meta Cloud API send for the rendered template.
   Done when: a real send produces both an outbound message and an outcome report that
   RE's provider-event ingest persists and finalizes (terminal state, no downgrade).
3. **Outcome reporter.** The authenticated callback path to RE, contract per §4-IN.
   Done when: unknown identity, malformed, late-contradictory and happy-path reports all
   behave exactly as `test_delivery_outcome_events.py` asserts.
4. **Chatwoot conversation adapter.** Text conversations, bot-in-the-middle, staff
   handoff. Done when: an inbound conversation can produce an authenticated RE command
   (registration/lookup subset, `docs/v3/38` §5) and RE notifications surface in the
   thread; delivery-handoff correlation arrives with S4 (`docs/handoff/04`).
5. **Voice adapter last.** Voice is incubating structure only (contract §12, `docs/v3/40`
   T7 — explicitly NOT implemented, not normative). Same pattern as steps 2-3.

Definition of done for the whole gateway: a full loop — RE intent → gateway → provider →
outcome report → RE durable terminal state — is idempotent when any component replays.

## 7. Honest risks

- **Weak transport authentication.** The webhook transport is HTTPS with one static
  header (`webhook_delivery_provider.py:53-56`); no mTLS, no OAuth, no signature
  verification today. Acceptable for a single-clinic pilot on a private network; it is
  NOT acceptable as-is for anything exposed publicly or multi-tenant. Upgrading the
  callback adapter's credential validation is a deployment decision that must precede any
  real traffic (see handoff 07, deployment checklist).
- **Outcome delivery depends on the gateway calling back.** RE mitigates with the
  reconcile polling backstop, but reconcile frequency and the gateway's own durability
  are unproven until someone runs the loop end to end.
- **Single-clinic scale assumptions.** RE is built multi-tenant, but nothing has ever
  run more than test tenants. The tenant-fairness claim query still carries a benchmark
  obligation before any production-scale due backlog (`docs/v3/10` lines 72-74). Do not
  promise multi-clinic behavior from this codebase's history.
- **No gateway exists yet.** Everything in this document is direction, not code. Until
  step 1-3 of §6 exist, no real message can reach a patient (see `docs/handoff/01` §4).

## 8. Reading map and what this document does NOT change

Engineer starting on this: read in order — `docs/v3/36` §4 (escalation contract, the
policy RE owns), `docs/v3/10` (worker runtime, env contract, provider-event contract),
`docs/v3/38` §5 (bot principal trust model), then `docs/handoff/04` (the S4/Chatwoot
adapter surface this gateway will host).

Nothing in the codebase changed to produce this document; it records a decision. In
particular, it does NOT change the normative contracts above, does not add a gateway
package, and does not alter the webhook transport. If a future change contradicts
§2/§3/§5, update this document and the owning `docs/v3/` contract together — do not let
them drift.
