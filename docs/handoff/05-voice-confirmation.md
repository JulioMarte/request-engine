# Handoff 05 — Voice Confirmation Channel (Incubating)

The voice channel is **structure only**. Doc 36 §12 is the amendment that admits it; it is
**normative only once implemented with evidence**, like every other F7 slice. Verified
against this branch at `063332fc`.

## 1. What exists (and what deliberately does not)

Exists:

- `voice` parses in `channel_policy`: it is in `_ENDPOINT_CHANNELS`
  (`modules/communications/domain/delivery_policy.py:14-20`) and maps to endpoint channel
  `phone`, the same endpoint `sms` maps to. A `channel_policy` with `channels: ["voice"]`
  passes `parse_delivery_policy` validation today.
- The escalation walk treats `voice` as a candidate channel through its `phone` endpoint
  (`modules/communications/adapters/db/escalation_next_channel.py:5-9`), and the same note
  records the honest caveat: sms/voice share the phone endpoint, so the pinned contact
  point resolves to the first policy route for that endpoint at dispatch time.
- Task and confirmation-intent semantics are channel-agnostic; the outcome callback
  contract is the provider-event surface (doc 36 §12).

Does **not** exist — deliberately (doc 40 T7 non-goals; doc 36 §0.2/§9/§12):

- no voice transport, no TTS, no conversation state, no agent runtime, no provider, no
  evidence, no tests. The only registered delivery provider is `WebhookDeliveryProvider`
  (key `webhook`, `bootstrap/communication_providers.py`).
- Honest correction to the plan: doc 40 T2 said migration `0026` would carry "voice
  channel vocabulary (structure only)". The landed `0026_s3_escalation_lineage.py`
  contains **no voice-specific DDL** — no column or CHECK names `voice`. Voice admission
  today lives only in Python policy parsing. Nothing is broken, but the migration-level
  vocabulary claim in doc 40 T2 did not land as written.

## 2. What a future implementation must build (external gateway, never inside RE)

Per doc 36 §12/§9: an external gateway executes calls; RE owns the confirmation intent and
records the reported outcome through the same fenced finalize.

1. **A voice-capable transport registered as a provider.** Implement
   `CommunicationDeliveryProvider.send`/`lookup` (contract in
   `modules/communications/contracts/delivery.py`) and register it in
   `build_communication_delivery_providers`. Dispatch binding happens **at dispatch, not
   at task creation**, by provider key (`resolve_provider_key`,
   `delivery_policy.py:96-113`).
2. **An outcome callback through the provider-event surface.** Voice reports enter like
   any other transport outcome: authenticated callback → `ingest_provider_callback` →
   persisted ProviderEvent → fenced finalize. The handler must be registered under the
   voice connection key in `build_communication_provider_event_handlers`; an unmatched
   report fails loud. Out-of-vocabulary or malformed reports become **rejected durable
   facts**, never guessed delivery state (`docs/v3/10` payload contract).
3. **A confirmation semantic command the voice session can trigger.** Authenticated,
   idempotent, tenant-scoped — the same discipline as every n8n/provider callback. The
   closed intent is `appointments.confirm_attendance` (or the S4 inbound lowering of it);
   the gateway performs NLU, RE validates and executes. Never direct DB mutation.

One nuance verified in code, stated honestly: dispatch binding is **provider-key-based,
not channel-capability-based**. If a tenant set `channels: ["voice"]` today with the
webhook provider configured, the task would dispatch a `channel: "voice"` handoff to the
webhook transport verbatim — it does **not** fail durably for lack of a voice transport.
The durable `delivery_configuration_invalid` failure happens only when **zero** providers
are configured (`scheduled_delivery.py:66-68`) or the recipient has no usable verified
phone contact point. Until a real voice transport exists, no production tenant policy
should list `voice` — nothing enforces that.

## 3. Provider landscape (honest, no fake certainty)

Not verified against any vendor integration in this repo — this is framing, not fact:

- **Conversational voice platforms** (Vapi, Retell, Twilio + an LLM layer): can run an
  actual Spanish conversation and report structured outcomes via webhook. Cost, latency
  and Spanish (Dominican) dialect handling are all open engineering questions; accents,
  background noise and "sí" vs "no" confusion on a phone line are real failure modes, not
  hypothetical ones.
- **Dumb IVR** (keyed responses): far simpler and cheaper, but "presione 1 para confirmar"
  is a worse fit for the patient population and the reschedule ask ("no puedo, muévame
  para el jueves") is exactly what IVR cannot capture — it would degrade to a human-review
  demand.

The confirmation use case — a yes/no plus an optional reschedule ask — defines the
complexity floor: it is below a general agent, but above a beep-and-record. Spanish
(Dominican) handling is a genuine risk item and should be tested with real calls before
any commitment, not assumed from vendor demos.

## 4. Sequencing recommendation

- **Voice last.** Run the text (WhatsApp) loop end-to-end with real patients first:
  S4 inbound, the day board, and real-world confirmation rates are prerequisites with
  far higher product value (contract §0.1 success criteria are all text-first). Voice
  builds on the same S4 intent lowering, so the text loop is the foundation either way.
- **If the owner asks for voice early**, the minimum viable path needs no agent and no
  voice channel at all: an **operator-initiated call task plus manual outcome recording**.
  The secretary calls the patient herself, then records the outcome (confirmed/declined/
  unreachable) as a typed RE command. This is honest (the fact is operator-asserted,
  `source_kind=operator`), it is durable, and it does not fabricate a voice transport
  that does not exist.

## 5. Open owner decisions

1. **When**: is voice needed before the text loop is proven with real patients? (The
   recommendation is no.)
2. **Minimum day-1 voice semantics**: confirmation-only (yes/no) vs confirmation + free
   reschedule ask. The latter forces an S4-grade intent boundary into the voice gateway
   from day one.
3. **Provider choice and cost ceiling** per call, and whether Dominican Spanish quality
   is an acceptance criterion (it should be, for the patient population in contract §0.1).
4. **Consent and recording policy**: whether calls are recorded, and where that consent
   fact lives — RE must own any durable fact it depends on; the gateway cannot.
