# Handoff 01 — Product Roadmap State

What the product is, what is actually shipped, what comes next, and what does **not**
exist despite sounding like it might. Verified against `development` at `a8760d9f`
(Sep 2026); migrations head `0026_s3_escalation_lineage`.

## 1. What the product IS

Authoritative: `docs/v3/36-front-desk-operations-contract.md` §0.1.

One primary user: **the receptionist / personal medical secretary of a small
Dominican Republic medical practice.** Receptionist + WhatsApp bot doing the
coordination work she does today by hand: confirmations that arrive by WhatsApp
become facts without her typing them; reminders send themselves; freed slots trigger
waitlist offers; "voy 20 min tarde" becomes a durable fact on a board; after-hours
"quiero cita" becomes a durable request for the morning.

It is **not** a patient-management system, not a clinical record, not billing.

Falsifiable success criteria (judged in the practice, not in the repo) — contract §0.1:

1. Patient confirmation/lateness/cancellation recorded without the secretary relaying
   it manually.
2. Reminders and confirmations send without manual action per message.
3. During a power/internet outage, patient-side messages still mutate authoritative
   state (the appointment truth lives where the light does not go out).
4. She can answer "who is coming, who confirmed, who is late, who can move" from one
   surface.
5. **The week-3 test: if she still keeps the real appointment book on paper or
   WhatsApp, F7 has failed — regardless of technical correctness.**

Design stance (inherited from F6): external transport/bot layers execute delivery and
conversation; Request Engine owns delivery truth, escalation policy, identity binding,
intent validation and every typed mutation. *The external layer proposes, RE disposes.*

## 2. What is SHIPPED (merged to `development`)

All below are integrated with exact-head CI evidence; each has a normative doc.

| Slice | What it does | Doc |
|---|---|---|
| F5 Operational Recovery + Communications | recovery proposals/sweeps, freshness tracking, bump guards, escalation policy over Booking/Queue/Catalog; communications as durable transactional intent | `docs/v3/32`, `33`, `34` |
| F6 external-agent operational tooling | bounded typed lookup/read + guarded mutation tools for external agents/copilots (no conversation/NLU inside RE); contract `docs/v3/35` — note `docs/README.md` still gates the "delivered" label on the external-agent DoD | `docs/v3/35` |
| F7a remote delivery transport (PR #104) | webhook `CommunicationDeliveryProvider` (`send`/`lookup`), delivery-attempt handoff with deterministic identity/dedupe, AMBIGUOUS→reconcile-first semantics, bounded reconcile + poison path | `docs/v3/36` §3 |
| F7d reservation arrival estimates (PR #104) | late-ETA facts on reservations, closed validation rules | `docs/v3/36` §6 |
| S0b party registry (PR #105) | tenancy-owned Party/contact-point/identity-document registry, operator-asserted verification, bot principal creation with placeholder naming, convergent phone identity, accent-folded lookup, operator-granted correction commands | `docs/v3/38`, plan `39` |
| S0b-R2 authority & history (PR #106) | two orthogonal attribution facts (`source_kind` operator/subject × declared `platform`), acting-operator relay gated by `platform.acting_for_operator` (verified same-transaction, fail-closed), versioned revision ledger with rollback, staff contact verification hardening | `docs/v3/38` §9 |
| S3 delivery escalation (PR #107) | provider-event outcome ingestion into fenced finalize (FU-2), sequential channel fallback with lineage, guard policy (max escalations + contact fatigue) with terminal facts `fatigue_limited`/`unreachable`, retired legacy delivery executor (FU-3), disarmed NOT_FOUND vocabulary + explicit `attempt_no` (FU-4), voice channel admitted only as incubating structure (T7) | `docs/v3/36` §4, plan `docs/v3/40` |

Migration line head: **`0026_s3_escalation_lineage`** (escalation lineage columns,
ledger table, `channel_policy` guard schema, voice vocabulary structure-only).

## 3. The reordered roadmap (Round-3 reordering, `docs/v3/37` round-3 section)

The round-3 usability audit found the transactional core operable but the product
without a front door (R3-1..R3-5 in `docs/v3/37`). Reordered build order:

```text
S0b party registry            DONE (PR #105 + #106)
S3 escalation                 DONE (PR #107)
day board (FU-1)              NEXT — see docs/handoff/02
S5 triage (F7e subset)        see docs/handoff/03
S4 inbound (F7c + R3-4)       see docs/handoff/04
S6 after-hours (F7f)          see docs/handoff/05
```

- **Day board (FU-1):** who is coming / confirmed / late / movable, for reservations
  AND attendance state. Goal criterion 4 is NOT-MET today: no day view exists at any
  layer; the secretary polls reservation-by-reservation. R3-2 (unified day agenda
  read) folds into this lane. Registered as FU-1 in `docs/v3/37`'s follow-ups table.
- **S5 triage:** the §7 semantic contract (`operator_select`, `recall_hold`, `skip`)
  — urgent selection, squeeze-in, stepped-out currently have zero truthful
  representation; every workaround fabricates durable lies.
- **S4 inbound:** F7c inbound interpretation boundary plus the R3-4 bot-as-subject
  authority mode and delivery-handoff correlation.
- **S6 after-hours:** F7f durable intake, application-composition slice, no core
  change.

Handoff documents for the remaining slices are `docs/handoff/02..05` (being produced
in parallel; assume they exist or are imminent when you read this).

## 4. What is NOT built — do not assume otherwise

Brutal version: **the repo is pre-first-deployment.** Nothing is running anywhere.

- **No Chatwoot/WhatsApp integration exists.** F7a built the webhook transport
  protocol and provider machinery, but there is **no real external transport consumer
  deployed** — no tenant has ever received a message through it.
- **No voice transport.** The voice channel is incubating structure only (contract
  §12, S3 T7): vocabulary and schema shape, explicitly NOT implemented, not normative.
- **No inbound message processing.** F7c is TARGET. Today nothing reads a patient's
  WhatsApp message and turns it into state; a patient's "voy 20 min tarde" cannot
  reach the system yet.
- **No day board.** FU-1 is unbuilt; criterion 4 fails structurally (round-3 audit).
- **Nothing deployed to production.** `docs/README.md`: pre-customer and
  pre-production. Released V3 is reproducible release provenance, not a running
  system.

## 5. Where the truth lives

```text
docs/v3/36  F7 front-desk contract (normative; §0.1 goal, §4 escalation,
            §7 triage semantics, §12 voice incubating)
docs/v3/37  F7 implementation plan + round-3 reordering + FU-1..FU-7 registry
docs/v3/38  S0b party registry contract (§9 = R2 authority/attribution/history)
docs/v3/39  S0b plan
docs/v3/40  S3 escalation plan (T1-T8, review dispositions, deferred concerns)
docs/v3/12  cross-tenant shared capacity + http bootstrap composition note
docs/v3/10  worker runtime hardening (env contract, fencing, executor)
docs/testing/README.md          test architecture + proof lane ownership
docs/testing/current-guarantees.toml    INV-* guarantee inventory (normative)
docs/testing/current-proof-map.toml     guarantee -> representative proof mapping
docs/testing/evidence-authoring-guide.md  how to write a proof that can fail
```

Precedence: a normative `docs/v3/<contract>` supersedes older baseline statements
where it explicitly says so; `docs/README.md` §11 is the map. `docs/legacy/**` is
non-authoritative.

Operational survival rules are in the sibling document
`docs/handoff/00-repository-operating-manual.md` — read it before your first push.
