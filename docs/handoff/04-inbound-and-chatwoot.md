# Handoff 04 — S4 Inbound Interpretation Boundary and the Chatwoot Integration

What S4 (`F7c`) is, what already exists, what a Chatwoot adapter must implement on both
directions, and what is still an owner decision. Verified against this branch at
`063332fc`; migrations head `0026_s3_escalation_lineage`.

Normative sources: `docs/v3/36-front-desk-operations-contract.md` §5 (F7c contract),
`docs/v3/37-f7-implementation-plan.md` (S4 section + R3-4),
`docs/v3/38-s0b-party-registry-contract.md` §9.1/§9.2, `docs/v3/10-worker-runtime-hardening.md`
(provider-event payload contract).

## 1. The problem

Request Engine owns **WHAT an inbound message may mutate**; the external transport layer
owns NLU and conversation. Rule (contract §1): *the external layer proposes, RE disposes* —
every inbound-sourced mutation enters as an authenticated, idempotent, tenant-scoped
semantic command through the owning module's published contract. Ambiguity resolves to a
human-review demand, never a guess.

Today there is **no inbound surface at all**. Honest inventory of what can enter RE from
outside:

- Delivery **outcome reports** (delivered/failed/accepted) via the authenticated
  provider-event callback surface (`platform/events/callbacks.py`:
  `ingest_provider_callback`). That is the only inbound provider fact today, and it
  mutates delivery state only.
- Nothing else. There is no HTTP route for patient messages, no intent parsing, no
  identity binding, no human-review demand surface.

Doc 36 §5 is the normative contract S4 must implement:

- **Identity binding (prerequisite):** an inbound message may act for a party only when it
  maps to a **verified contact point** bound to that party, plus a valid
  `representations` authority when acting for another subject. Unbound sender, ambiguous
  binding or missing authority → **human-review demand** (a durable requests-lifecycle
  item), never a mutation.
- **Intent set v1 (closed):** confirm attendance → `appointments.confirm_attendance`
  (accepted); decline attendance → same command (declined); cancel reservation →
  `appointments.cancel`; arrival estimate → `appointments.record_arrival_estimate`
  (F7d, landed via PR #104); waitlist offer accept/decline → existing commands; anything
  else → human-review demand. Refusal is the default; adding intents requires a contract
  amendment.
- **Rules:** each lowered command runs its normal idempotency envelope and revision
  fencing; interpretation is deterministic and closed (the NLU may score, RE validates);
  replayed inbound facts are no-ops; contradiction after irreversible consequence becomes
  a human-review demand; **retract forward, never erase**; conversation content lives in
  the transport layer — RE records only typed facts and command outcomes.

## 2. R3-4 bot-as-subject authority: what exists vs what S4 adds

R3-4 (doc 37): a bot relaying a patient's own fact through operator override durably
misattributes it (`source_kind=operator` for the patient's ETA). S0b-R2 §9.1 already fixed
the **attribution** half; S4 owns the **authority** half.

Already exists (verified in code):

- **Two-dimensional attribution** — `source_kind` (`operator`|`subject`, whose authority)
  × `platform` (declared surface, ≤64 chars, verbatim, never an authorization input).
  Derived server-side: a HUMAN principal is `operator`; an INTEGRATION/SYSTEM principal
  acting without an admitted relay is `subject`
  (`modules/tenancy/api/party_registry_dependencies.py`, `source_kind()`). Never read from
  a request body.
- **Acting-operator relay** — an integration principal may execute operator-directed
  mutations only with the `X-RE-Acting-Operator` header and the
  `platform.acting_for_operator` admission permission. RE verifies in-transaction that the
  referenced principal exists, is active, is HUMAN, same organization; capability checks
  then run against the operator's grants; the bot cannot launder authority
  (`platform/security/acting_operator.py`; headers at lines 28-29).
- **ActorContext fields** — `platform`, `acting_operator_principal_id`,
  `technical_principal_id` (`platform/security/context.py`), so audit keeps both the
  technical caller and the attributed operator.
- **Deployment operator resolver** — `entrypoints/http/operator_resolution.py`:
  `DeploymentOperatorActorResolver` resolves the referenced operator against authoritative
  principal state; the deployment supplies its grant model through the
  `OperatorCapabilitySource` port (wired in `entrypoints/http/app.py`). A deployment
  without a capability source **cannot** materialize relay grants: the relay raises
  `OperatorResolutionUnavailable`, mapped to **503** `operator_resolution_unavailable`
  (`entrypoints/http/error_handlers.py:23-32`) — misconfiguration, not a 403. An
  unresolvable/inactive operator fails closed with 403.

What S4 must add:

1. **Verified-contact-point binding as a subject-authority source** (R3-4's core ask).
   Today a registered contact point grants *nothing* inbound — doc 38 §7 says so
   explicitly ("a registered contact point does not let an inbound message act for the
   Party until the S4 verified-contact-point authority path exists").
2. **A delivery-handoff correlation block** (subject/purpose/conversation key) so an
   inbound message can be tied to the outbound delivery that provoked it.
3. The closed intent set lowering to owner commands, and the human-review demand surface.
4. Note honestly: S0b delivered the Party registry but **not** a representations API;
   representation-based acting-for still needs its own surface or an explicit owner
   decision to keep verified-contact-point as the only inbound subject path.

## 3. Chatwoot integration runbook skeleton

Doc 37's composition contract: tenants select the transport per channel via
`channel_policy.provider_key = "webhook"`; the reference worker factory registers
`WebhookDeliveryProvider` under key `webhook` when
`REQUEST_ENGINE_WEBHOOK_BASE_URL` is configured (`bootstrap/communication_providers.py`;
env contract in `docs/v3/10` §"Reference worker factory environment contract":
`REQUEST_ENGINE_WEBHOOK_BASE_URL` required, `REQUEST_ENGINE_WEBHOOK_AUTH_HEADER` optional
`Header-Name: value`, plus worker/app DB URLs, `REQUEST_ENGINE_WORKER_PRINCIPAL_ID`,
`REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY`).

### Outbound (RE → Chatwoot adapter): delivery handoff

`WebhookDeliveryProvider.send`
(`modules/communications/adapters/transport/webhook_delivery_provider.py`) POSTs HTTPS:

```text
delivery_id, communication_task_id, dedupe_key, attempt_no, provider_key, channel,
recipient {contact_point_id, destination}, content {template_key, template_version,
render_context}, expires_at, reconcile_after_seconds
```

The Chatwoot-side adapter must:

- **dedupe on the delivery identity** — an RE retry must never double-send;
- 2xx response = handoff accepted (respond with optional `provider_message_id`);
  non-2xx (including 3xx — RE refuses redirects) = retryable failure, task returns to
  `pending`;
- serve `GET {base_url}/status/{dedupe_key}` for reconcile polling; answer only
  `delivered` or `failed` — anything else (and 404) keeps the delivery AMBIGUOUS and
  schedules another reconcile; a not-found answer must never trigger a resend;
- execute the actual WhatsApp send/conversation. Content is always rendered from the
  template context; the transport layer never invents content.

### Inbound (Chatwoot adapter → RE): outcome reports

Outcome reports enter through the **provider-event surface** — persist-before-
interpretation, deduped on `organization + provider_key + connection_key +
provider_event_id`. The reference handler is registered under the connection key
`(provider_key="webhook", connection_key="primary")`
(`bootstrap/communication_providers.py`); an unmatched report fails loud, never silent.

Payload contract (`docs/v3/10` §"Reference handler registration"):

- `dedupe_key` (required) — delivery is resolved authoritatively from the authenticated
  lease's `(provider_key, connection_key)` + this key; a client-sent delivery id is never
  trusted; a report about an unknown key is a durable no-op;
- `status` (required) — one of `accepted`, `delivered`, `failed`; anything outside the
  vocabulary is a **typed rejection** (durable rejected ProviderEvent fact), never a
  guessed state; `retryable`, `provider_message_id`, `result_data` optional;
- finalize is fenced and terminal-monotonic through the same path as reconcile polling —
  replay is a no-op and a late contradictory report can never downgrade a terminal state.

What the deployment must build on this side: an **authenticated callback HTTP route**
using `ingest_provider_callback` with a deployment-supplied
`ProviderCallbackAuthenticator` that binds `(organization_id, provider_key,
connection_key)` — none of that may come from the payload. RE ships the mechanism, not
the route/authentication; that is deployment work.

### Relayed operator actions

When the Chatwoot layer relays a *staff* action (e.g. an agent corrects a record), it must
authenticate as its own integration principal with the restricted S0b grant set
(`parties.register`, `parties.add_contact_point`, `parties.lookup` only — doc 38 §5) and
present `X-RE-Acting-Operator` plus the deployment's `OperatorCapabilitySource`. A
deployment that has not supplied its grant model gets 503 on every relay; bots without
the admission permission get 403.

## 4. Staff verification loop (doc 38 §9.2) — already landed, no inbound parsing

Staff (operator) principals register their own administrative contact
(`staff.manage_own_admin_contact`) and confirm it with a one-time 6-digit code
(`staff.confirm_own_admin_contact`). Verified flow
(`modules/tenancy/adapters/db/principal_contact_verification_commands.py`):

- one transaction: row-lock the contact, reject a re-request while an unexpired code is
  pending, generate the code, store **sha256 hash** with 15-minute expiry and 5-attempt
  limit, and append ONE outbox event `staff.contact_verification_requested.v1` carrying
  the code verbatim as durable transactional intent;
- delivery is external: outbox → deployment publisher → transport → WhatsApp (tenancy
  README). RE owns the intent, never the transport;
- confirmation is a capability-gated RE command; integration/relay callers get a typed
  403. Replay never re-exposes a code. No inbound parsing is needed — a human reads the
  code and enters it.

This is the template for any future inbound round-trip: durable intent out, typed command
back in, no free-text trust assertions.

## 5. Proof expectations and open owner decisions

Proof expectations (contract §10 F7c): unbound sender → review demand with **zero state
mutation**; each closed intent lowers to its owner command with subject authority resolved
in-transaction; replayed message is a no-op; ambiguous intent → review demand. These need
PostgreSQL-backed evidence like every other slice — none exist yet.

Open owner decisions (raise explicitly, do not guess):

1. **Which intents are automatable day 1** — the closed set is six; the owner may want a
   smaller day-1 set (e.g. attendance confirmation only) with everything else routed to
   review.
2. **Conversation ownership** — who owns the WhatsApp conversation thread (Chatwoot
   inbox vs bot persona), and what RE records when a conversation is handed between a bot
   and a human agent mid-intent.
3. **Language** — Dominican Spanish phrasing for each intent ("confirmo", "no puedo",
   "voy 20 min tarde") and what happens on mixed/unclear language: the closed intent set
   means anything unparseable becomes a review demand, but the owner should confirm the
   review UX.
