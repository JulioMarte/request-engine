# S0b — Party Registry & Lookup Contract (F7 follow-on)

Status: normative for the S0b slice.
Owner module: `tenancy` (per `docs/10-module-ownership-map.md`: Party, PartyContactPoint
identity/normalization; the hard tenant/authority boundary).
Supersedes nothing; extends the V3 baseline. Product context: `docs/v3/36` §0.1.

## 0. Goal and falsifiable criteria

The front-desk product is blocked on a structural fact: no API can create a Party or a
contact point, and no lookup by phone/name/document exists. S0b removes that blocker.

This slice succeeds when:

1. A receptionist (human operator principal) can register a patient with contact points
   and a cédula through the public API, and the created row world is exactly what
   booking/queue/communications already consume (`subject_party_id` targets).
2. An unknown WhatsApp number can be turned into a Party by a bot principal via the same
   public API, and the contact point lands **unverified** — it never enters the verified
   delivery path until an operator confirms it.
3. A lookup for a shared family number returns **every** person bound to it, not one.
4. A cédula is a unique, normalized, tenant-scoped identity fact: duplicate registration
   of the same cédula for a different Party is rejected atomically under concurrency.
5. No CRM/medical profile fields are invented: Party stays identity-only.

## 1. Product decisions (owner, 2026-08-31)

1. **Verification is operator-asserted.** The creator confirms the contact belongs to the
   person at creation time. The creator may be a human operator principal **or a bot
   operating above Request Engine** (planned: Chatwoot intermediary). A contact point
   created by a bot principal starts `verified = false`.
2. **Bot auto-create is included in S0b**, not deferred to S4. The bot layer creates the
   Party via the same public capability; the R3-4 bot-as-subject authority mode (acting
   *for* a subject on durable facts) remains an S4 concern.
3. **Shared phone numbers are allowed** across Parties (family reality). Phone lookup is
   inherently multi-match; callers must handle a list.
4. **Search covers name, phone, and identity document (cédula).**
5. **Bot-created Parties get a visible placeholder name.** A bot principal
   creates Parties with `display_name = "WhatsApp <normalized number>"`; the
   placeholder is a visible label only and is corrected by an operator via
   `parties.rename`.

## 2. Schema additions (migration `0023`, append-only)

The V3 baseline already owns `request_engine.parties` and `request_engine.party_contact_points`
(frozen in `0001_initial`). S0b adds, without altering frozen columns:

- `request_engine.party_identity_documents`:
  - `organization_id`, `party_id` (tenant composite FK to parties),
  - `kind` CHECK in (`cedula`, `passport`), `normalized_value` text,
  - `active` bool default true, standard timestamps,
  - partial UNIQUE INDEX `(organization_id, kind, normalized_value) WHERE active` —
    a document value of a given kind belongs to at most one **active** identity per
    tenant (I-S0b-1: uniqueness holds among active rows); the same index serves the
    exact-lookup predicate,
  - partial UNIQUE INDEX `(organization_id, party_id, kind) WHERE active` so one Party
    holds at most one active document per kind.
- Attribution columns, additive:
  - `parties.created_by_principal_id uuid NULL`,
  - `party_contact_points.created_by_principal_id uuid NULL`,
  - `party_identity_documents.created_by_principal_id uuid NULL`,
  - `party_contact_points.registered_via text NULL CHECK in ('operator','bot')`.
- `party_contact_points` lookup index `(organization_id, normalized_value, channel)
  WHERE active` (migration `0024`) serving the phone lookup predicate.
- `party_contact_points` guard trigger (I-S0b-4 backstop): an UPDATE that would flip
  `verified` from true downward is rejected by the database, so verification monotonicity
  holds even against direct runtime-role SQL, not only through the confirm command.

Attribution is a **durable fact about who registered**, never an authority source: the
trusted boundary remains the authenticated principal (see §5).

## 3. Normalization (tenancy-owned, pure, unit-tested)

- `phone` / `whatsapp`: E.164 digits with leading `+`; Dominican local formats
  (`(809) 555-1234`, `809-555-1234`, `1 809 555 1234`) normalize to
  `+18095551234`, and `18295551234` normalizes to `+18295551234`. Reject values with
  fewer than 10 / more than 15 digits after normalization.
- `cedula`: digits only (`402-1234567-8` → `40212345678`); reject anything that is not
  exactly 11 digits after normalization.
- `passport`: uppercase alphanumerics, 6–17 chars.
- `display_name` search key: lowercase, Unicode NFKD, accent-stripped, whitespace
  collapsed — computed at query time from `display_name`, no extra stored column.

## 4. Public surface (tenancy `api`, capability-gated)

Commands (semantic, idempotent via standard replay keys):

- `parties.register` — create a Party (`party_kind = 'person'` in S0b) with optional
  initial contact points and optional one document per kind. `registered_via` is derived
  server-side from the principal's authority mode (`operator` vs `bot`), never from a
  client-sent field. Contact points submitted by an operator principal are created
  `verified = true`; by a bot principal, `verified = false`.
- `parties.add_contact_point` — same verification rules, on an existing Party.
- `parties.confirm_contact_point` — **operator-only** command flipping an unverified
  contact point to `verified = true`. Bot principals receive `403` by capability gate,
  not by convention.

Operator-granted correction commands (week-1 front-desk reality: facts get corrected).
All four are grant-gated like every other capability, are **never granted to bot
principals** (§5), are audited and idempotent via standard replay keys, and emit no
outbox events (`parties.register` remains the only outbox emitter — its
`party.registered.v1` payload contract is `party_id`, `display_name`,
`contact_point_count`: consumer-visible, PII-minimal by decision). Party
existence/active is checked with a row lock; corrections targeting an inactive party
fail closed with the typed not-found:

- `parties.rename` — correct a Party `display_name`. The display name is a mutable
  label; identity facts, contact points and documents are untouched. No DB guard
  blocks it (the documents guard is separate).
- `parties.add_document` — add one identity document to an **existing** Party (e.g.
  the cédula learned on a second visit). Normalization matches `parties.register`
  and the same unique active-value backstop applies: duplicate values map to the
  typed conflict enriched with the holder Party (id + display name); a second
  active document of the same kind for the same Party is a typed conflict too.
- `parties.deactivate_contact_point` — set a contact point's `active = false`.
  `verified` is untouched, so verification monotonicity (I-S0b-4) is preserved.
- `parties.deactivate` — set `parties.active = false`. Lookups already filter
  `p.active`, so a deactivated Party disappears from every lookup mode.
  Re-deactivating an inactive Party succeeds idempotently.

Queries (read-only):

- `parties.lookup` with exactly one of `phone`, `document`, `name`:
  - `phone`: normalized exact match across `phone`/`whatsapp` contact points; may
    return many Parties (shared family number);
  - `document`: normalized exact match on `(kind, value)`;
  - `name`: accent-insensitive prefix match on `display_name`, capped result page.
- Returns Party identity, active contact points with `verified` flag, and documents.
  Never returns authority or representation internals.

All new capabilities register in the capability registry with the standard
tenant-isolation and idempotency gates; bot principals get only the creation/lookup
subset via their principal capability set.

## 5. Trust and attribution model (Chatwoot intermediary)

- The intermediary (Chatwoot/bot layer) authenticates as its own **bot principal** with
  a restricted capability set. It has no more authority than its capabilities grant.
- Bot provisioning recipe: grant exactly `parties.register`,
  `parties.add_contact_point` and `parties.lookup` — never
  `parties.confirm_contact_point`, `parties.rename`, `parties.add_document`,
  `parties.deactivate_contact_point` or `parties.deactivate`.
- `registered_via` and `created_by_principal_id` answer *"who put this fact in the
  system"* for audits and support. They are descriptive, not decisional.
- Operator/bot attribution (`registered_via`) derives from the authenticated
  principal's kind: `HUMAN` principals are operators, `INTEGRATION`/`SYSTEM`
  principals are bots. It never derives from a capability key — capability sets
  decide what a principal may do; the principal kind decides how its writes are
  attributed.
- Attributing a human agent behind the intermediary is that layer's concern; RE stores
  only the authenticated principal identity. If Chatwoot later supplies a staff-actor
  hint, it must arrive through an authenticated operator principal or an explicit
  operator override contract — never as a free-text trust assertion.

## 6. Invariants and race matrix (V3-Ixx alignment)

- **I-S0b-1**: a document value of a given kind is unique among active rows per tenant.
  Concurrent `parties.register` with the same cédula for two different Parties: exactly
  one commits; the loser gets the typed conflict (409), proven with two independent
  transactions on real PostgreSQL.
- **I-S0b-2**: at most one active document per `(party, kind)`.
- **I-S0b-3**: contact point uniqueness stays `(organization_id, party_id, channel,
  normalized_value)` (frozen); the same number may belong to several Parties by design.
- **I-S0b-4**: `verified` transitions are monotone upward through the confirm command;
  no command path silently downgrades verification.
- **I-S0b-5**: bot-created contact points are never `verified` at creation, regardless
  of client-sent fields (server-derived, like F7d `source_kind`).
- Lookup paths take no locks beyond the tenant RLS context and are safe under
  concurrent registration (multi-match is the expected outcome, not an anomaly).

## 7. Anti-goals

- No CRM profile: no birth date, address, insurance, medical history, notes-free-text.
- No implicit authority: a registered contact point does not let an inbound message act
  for the Party until the S4 verified-contact-point authority path exists.
- No silent merge or dedup of Parties that share a phone number.
- No verified-by-default paths for bot principals.

## 8. Proofs

- Module tests: normalization table (DR formats), verification derivation by principal
  kind, capability-gate rejections, lookup multi-match shape.
- PostgreSQL tests (real 18): cédula unique backstop race (two connections, one loser),
  confirm-command monotonicity under concurrent replay, shared-phone multi-party lookup,
  bot-created contact point never verified.
- HTTP surface + tenant isolation: new routes registered in the isolation matrix; bot
  principal cannot reach `confirm_contact_point`.
- Canonical lane: `python scripts/ci/ci_jobs.py python-quality` plus the PostgreSQL
  runner that owns tenancy/party proofs per `docs/testing/README.md`.
