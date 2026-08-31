# F7 Front-Desk Operations Contract

Status: normative contract for `feature/f7-front-desk-operations`. Slices land append-only; each slice is normative only once its implementation and evidence are merged. Not-yet-implemented slices below are TARGET.

## 0. Product framing

### 0.1 Product goal (authoritative)

F7 exists for one primary user: **the receptionist / personal medical secretary of a small
Dominican Republic medical practice.** It is not a patient-management system, not a clinical
record, and not a billing tool. It is the operational companion that does the coordination
work she does today by hand:

- know who is actually coming today (confirmations that arrive by WhatsApp become facts
  without her typing them);
- reduce no-shows (reminders send themselves; a freed slot triggers a waitlist offer
  without her acting);
- absorb late arrivals ("voy 20 min tarde" becomes a durable fact the board shows);
- communicate day-of changes (doctor running late -> waiting patients are told, not called
  one by one);
- capture after-hours demand (a "quiero cita" at 11pm is a durable request for the morning);
- reach unreachable patients (channel escalation instead of silence).

Success criteria (falsifiable, judged in the practice, not in the repo):

1. A patient's confirmation, lateness or cancellation is recorded without the secretary
   relaying it manually.
2. Reminders and confirmations send without manual action per message.
3. During a clinic power/internet outage, patient-side messages still mutate authoritative
   state (the appointment truth lives where the light does not go out).
4. She can answer "who is coming, who confirmed, who is late, who can move" from one
   surface without opening individual reservations.
5. **The week-3 test: if she still keeps the real appointment book on paper or WhatsApp,
   F7 has failed — regardless of technical correctness.**

### 0.2 Boundary stance

The design stance is the one already proven by F6:

> **Request Engine decides what is true, what to send, on which channel, when to escalate,
> and whether an inbound message may mutate state. External transport layers execute the
> delivery and the conversation, and report durable facts back.**

Request Engine does not host a conversational bot, an LLM, a voice runtime or a NLU engine
for F7 to be complete. The external layer is the best friend of the secretary; Request
Engine is the part of the system that never lies.

## 1. Connection-surface overview

```text
Patient / customer (WhatsApp, phone)
        |
        v
Messaging & voice transport layer (EXTERNAL: bots, console integrations, providers)
        |  executes sends, runs conversations, performs NLU,
        |  reports delivery and intent outcomes
        v
F7 front-desk surfaces
        |  delivery handoff + fenced outcome finalize (F7a)
        |  escalation policy + channel lineage (F7b)
        |  identity binding + intent validation + typed lowering (F7c)
        |  arrival-estimate fact (F7d)
        |  same-day selection facts/commands (F7e)
        v
F1-F6 owner modules (booking, queue, delivery, live_capacity, recovery, copilot)
```

Cross-cutting rule inherited from F6 and the recovery contract:

> **The external layer proposes. Request Engine disposes.** Every inbound-sourced mutation
> enters as an authenticated, idempotent, tenant-scoped semantic command through the owning
> module's published contract. Ambiguity resolves to a human-review demand, never a guess.

## 2. Slice set (closed, append-only)

| Slice | Name | Owner module | Status |
|---|---|---|---|
| F7a | Remote delivery transport | communications | implemented on `feature/f7-front-desk-operations` (PR #104) |
| F7b | Delivery escalation policy | communications | TARGET (depends on F7a) |
| F7c | Inbound interpretation boundary | communications + owners | TARGET (depends on F7d for late-ETA) |
| F7d | Reservation arrival estimates | booking | implemented on `feature/f7-front-desk-operations` (PR #104) |
| F7e | Same-day selection layer (subset) | queue | TARGET (own proof lane, later) |
| F7f | After-hours demand intake | application composition | TARGET (no core change) |

Adding another slice or another inbound intent requires this contract's amendment, a
published owner contract for any mutation, capability disposition and acceptance evidence.

## 3. F7a — Remote delivery transport

RE keeps the entire delivery state machine
(`CommunicationTask` -> `dispatch_task` -> `CommunicationDelivery` -> fenced finalize).
What changes is who performs the network I/O: a configured **remote transport provider**
implements the existing `CommunicationDeliveryProvider` protocol (`send` / `lookup`) over
an HTTPS webhook to the transport layer.

### Handoff contract

`send` delivers a **delivery attempt handoff**, not a fire-and-forget order:

```text
delivery identity (deterministic, derived from task + attempt_no)
dedupe_key
channel + provider_key
recipient (contact point id, endpoint value)
content reference (template key/version + render context)
expires_at
reconcile_after_seconds
```

### Semantics (must match the baseline communications execution semantics)

- transport must dedupe on the deterministic delivery identity; a RE retry must never
  double-send;
- `send` returns 2xx -> handoff accepted; non-2xx (including any 3xx redirect — redirects
  are refused so the static credential is never forwarded cross-origin or downgraded to
  http) -> retryable failure (task returns to `pending` with a new future attempt, per
  existing retry semantics);
- `send` transport exception (timeout, connection) -> **AMBIGUOUS**; reconciliation-first:
  RE queries `lookup` before any resend, never blind-retries;
- `lookup` maps the remote status to `delivered` / `failed` / `unknown` only; `unknown`
  and remote-404 keep the delivery **ambiguous** and schedule another reconcile — a
  not-found answer must never trigger a resend under a fresh identity;
- **the ambiguity loop is bounded by the task deadline**: the reconcile path applies the
  same `expires_at` gate as dispatch; when the deadline passes the task terminalizes with
  a durable failure fact (`delivery_deadline_exceeded`) and the delivery row keeps its
  true last state. An unreachable transport can never strand a task in `delivering`
  forever, and a delivered-before-deadline message is never reported failed;
- outcome reports arriving from the transport layer enter through the authenticated
  provider-event surface (persist-before-interpretation, deduped, fenced). Replay is a
  no-op. Only fenced finalize mutates delivery state; late contradictory results can never
  downgrade terminal states (existing rule, unchanged);
- **transport binding happens at dispatch, not at task creation**: a `channel_policy` may
  omit `provider_key`; an omitted key binds to the deployment's sole registered provider,
  and with zero or multiple providers the task fails durably (`delivery_configuration_invalid`)
  instead of retrying silently. Tasks declare channels; deployments declare transports.

F7a adds no new truth domain. It is a transport adapter plus wiring.

## 4. F7b — Delivery escalation policy

Baseline gap being closed: a definitive channel failure is currently terminal for the task.
F7b adds deterministic, auditable, **sequential** channel fallback owned by RE.

### Trigger vocabulary (closed — no DSL, no tenant-configurable triggers)

```text
delivery_deadline_missed   delivery not final delivered before the task deadline
definitive_failure         non-retryable failure on the current channel
recipient_unreachable      all contact points for the current channel exhausted
```

### Behavior

- On a trigger, the current channel attempt closes terminally (with its failure class);
  a **new** `CommunicationTask` is created for the next channel in the tenant
  `channel_policy` order, linked to the parent task (lineage of notification attempts,
  same lineage discipline as recovery actions).
- Escalation is **sequential, never parallel**: at most one live channel task per
  notification lineage.
- New task dedupe keys are deterministic (parent task + channel + escalation ordinal);
  replay is a no-op.
- Guards (tenant policy, closed defaults):
  - `max_escalations_per_task` (default 2);
  - **contact fatigue guard**: maximum outbound contacts per subject per day. A guard
    refusal closes the lineage as `fatigue_limited` — an operator-visible fact, never
    silence.
- Escalation decides **channel and timing only**. Content is always rendered from the
  template context; the transport layer never invents content.
- No remaining channels -> lineage closes terminal `unreachable`; visible to operator
  surfaces.

## 5. F7c — Inbound interpretation boundary

The external layer performs NLU. RE validates identity, authority and intent, then either
executes a typed owner command or refuses.

### Identity binding (prerequisite)

An inbound message may only act for a party when it maps to a **verified contact point**
bound to that party (and, when acting for another subject, a valid
`representations` authority of the supported kinds). Unbound sender, ambiguous binding, or
missing authority -> **human-review demand** (a durable requests-lifecycle item), never a
guess and never a state mutation.

### Intent set v1 (closed)

| Inbound intent | Lowers to | Notes |
|---|---|---|
| confirm attendance | `appointments.confirm_attendance` (accepted) | existing command |
| decline attendance | `appointments.confirm_attendance` (declined) | existing decline policy applies |
| cancel reservation | `appointments.cancel` | subject authority required |
| arrival estimate ("voy 20 min tarde") | `appointments.record_arrival_estimate` (F7d) | new fact, subject authority |
| waitlist offer accept | `waitlist.accept_offer` | existing command |
| waitlist offer decline | `waitlist.decline_offer` | existing command |
| anything else | human-review demand | refusal is the default |

Rules:

- each lowered command runs with its normal idempotency (tenant + principal + capability +
  client key + fingerprint) and revision fencing;
- the interpretation layer is deterministic and closed: the NLU may score, RE validates;
- late contradictory or replayed inbound facts follow the external-authority rule:
  idempotent replay is a no-op; contradiction after irreversible consequence becomes a
  human-review demand; **retract forward, never erase**;
- conversation content lives in the transport layer. RE records only typed facts and
  command outcomes.

## 6. F7d — Reservation arrival estimates

New durable fact in Booking, attached to a confirmed reservation:

- **at most one active arrival estimate per reservation**; history is append-only
  (a new estimate supersedes the previous one; superseded rows are immutable);
- fields: estimated arrival instant, source (`customer` | `operator`), asserting principal,
  asserted timestamp;
- **`source_kind` is derived server-side from the resolved authority mode** (operator
  override -> `operator`; subject/representation authority -> `customer`) and is not
  caller-supplied: provenance is decided by the clinic, never asserted by the patient;
- the recording command is idempotent, revision-fenced (`expected_revision`), and
  authority-gated exactly like attendance recording (subject scope via representations or
  operator override), with party authority resolved in-transaction;
- closed validation rules (advisory fact — no policy engine): an estimate in the past
  (already an arrival/check-in fact, not an estimate) and an estimate after the
  reservation interval end (the slot is gone; the fact can never be acted on) are
  rejected with a typed 422; an estimate before the interval start is legal (early
  arrival is real information); no monotonicity rule (supersede handles revisions);
- an active estimate is **advisory input**: receptionist surfaces may display it and F4
  projection may consume it as an input, but it must never fabricate certainty — the
  honest-unknown rule of F4 is unchanged (no estimate -> `unknown`, never invented);
- recording an estimate never mutates reservation status or capacity truth.

## 7. F7e — Same-day selection layer (subset)

Preserved unchanged: FIFO default and tiebreaker over `(admitted_at, id)`; position is
derived, never a stored counter; one active entry per subject per queue; no scoring, no
tenant-configurable policies.

Added closed facts/commands (each a named, audited, idempotent operator command):

```text
operator_select   call a specific waiting entry now; reason recorded from a closed reason set
recall_hold       entry temporarily not-callable until a condition
                  (closed kinds: until_time, until_event, until_customer_initiates);
                  reason is optional annotation, the gate is queue truth
skip              recorded non-terminal defer of the FIFO head; entry returns to waiting
```

- Reordering is expressed as ordered facts over the derived order, never a mutable
  position; the degenerate case (no holds, no priority facts, no override) must select
  byte-identically to today's `call_next`.
- Terminal exits (`no_show`, `leave`) remain the only permanent departures.
- Live capacity projection must honor recall holds: a held entry is not projected as
  imminent; where truth runs out the projection degrades honestly (`partial` /
  `indeterminate`), never guesses.

## 8. F7f — After-hours demand intake

Composition only, no new core semantics: after-hours demand lands via the existing public
`requests.submit` command against a tenant request definition; morning conversion into
bookings happens through existing owner commands at the application layer. F7f is an
application/vertical concern and owns no tables.

## 9. What F7 must never become

- a conversational engine, LLM runtime, NLU engine or voice runtime inside Request Engine;
- a generic workflow/rule engine (triggers, intents, gates and reasons are closed sets);
- a patient record, billing, insurance or inventory system (external authority; only the
  minimal typed facts defined here cross the boundary);
- parallel multi-channel delivery; auto-dispatch without operator commitment (F7e);
- content invention by the transport layer (escalation decides channel/timing only);
- a second delivery truth outside `communication_deliveries`.

## 10. Acceptance proofs (per slice; each lands with its implementation)

- F7a: replayed handoff never double-sends (transport dedupe proven); send exception
  produces AMBIGUOUS and a reconcile (not a resend); fenced finalize rejects stale/late
  contradictory reports; worker deployment keeps provider I/O outside DB locks.
- F7b: trigger -> exactly one new channel task with deterministic dedupe (replay no-op);
  no parallel live tasks in a lineage; fatigue guard refuses with visible terminal fact;
  PostgreSQL proof under concurrent escalation attempts.
- F7c: unbound sender -> review demand, zero state mutation; each closed intent lowers to
  its owner command with subject authority resolved in-transaction; replayed message is a
  no-op; ambiguous intent -> review demand.
- F7d: supersede preserves append-only history; one active estimate per reservation
  (concurrent PostgreSQL proof); authority/revision/idempotency gates; degenerate F4
  behavior unchanged without estimates.
- F7e: degenerate selection equivalence proof (no facts -> identical `call_next` result);
  held entries excluded from automatic selection and from imminent projection; every
  out-of-order move audited; concurrent PostgreSQL proof on the selection lock path.
- F7f: after-hours demand visible next morning; conversion uses only existing owner
  commands.

## 11. Migration plan

- Schema changes are new append-only Alembic revisions (next is `0022_...`).
  `0001_initial` and the frozen V3 candidate line remain untouched.
- Every new table: tenant-scoped (`organization_id` composite keys), FORCE RLS, identity
  immutability triggers where facts are append-only, partial unique indexes for active
  rows, backstop constraints at the DB layer.
- Existing commands, states and public APIs gain nothing breaking; every slice must keep
  the degenerate behavior of existing surfaces unchanged (see per-slice equivalence
  proofs).
