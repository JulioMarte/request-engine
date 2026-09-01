# S0b Implementation Plan — Party Registry & Lookup

Contract: `docs/v3/38-s0b-party-registry-contract.md` (normative).
Lane: `feature/s0b-party-registry` against `development`.
Predecessor: F7 merged as PR #104 (commit `fe49e938`).

## Build order

### T1 — Migration `0023_s0b_party_identity_documents`
- Append-only revision creating `party_identity_documents` + attribution columns
  (§2 of the contract).
- Includes partial unique per `(party, kind)` on active rows and the exact-lookup index.
- Proof: migration applies cleanly on the V3 baseline and after `0022`; frozen payload
  untouched (provenance lane stays green).

### T2 — Normalization + domain values (tenancy)
- Pure normalization for phone/whatsapp/cedula/passport and the name search key (§3).
- No Pydantic in domain/application; transport mapping stays in `api`.
- Module tests own the normalization table; no DB.

### T3 — Application commands + reader
- `parties.register`, `parties.add_contact_point`, `parties.confirm_contact_point`
  commands and the `parties.lookup` query on tenancy `application` Protocol surfaces.
- `registered_via` derived from the principal authority mode (same shape as F7d
  `source_kind` derivation); verification per §1.1/§4.
- One Session, one explicit transaction per command; no external I/O inside.

### T4 — DB adapters (tenancy `adapters/db`)
- Insert/read paths for parties, contact points, documents; exact + prefix lookups.
- Document uniqueness relies on the migration backstop; the command maps the typed
  conflict instead of pre-checking (pre-check is advisory only).

### T5 — API surface (tenancy `api`) + capability registry
- Routes for the three commands + lookup; Pydantic transport DTOs mapped at the edge.
- Register capabilities in the registry with tenant isolation; bot principal scope
  excludes `confirm_contact_point`.
- Add routes to the HTTP surface classification and the tenant isolation matrix.

### T6 — PostgreSQL proofs (tests/e2e + integration lane)
- Cédula duplicate race: two independent connections register the same document value
  for different parties; deterministic sync; exactly one winner, loser gets 409.
- Confirm monotonicity under replay; bot-created contact point never verified;
  shared-phone lookup returns all bound parties.

### T7 — Docs + governance
- `docs/README.md` map entry for `38`/`39`; tenancy `README.md` scope note.
- Doc-contract expectations updated for any mapped file touched (T3–T5).
- Effective-line budget respected; compact new files instead of ratcheting old ones.

## Review discipline

Same as F7: after implementation, independent adversarial review tracks (security,
operational, product-fitness, evidence audit) before requesting merge; fixes land on the
same branch; exact-head CI is the merge evidence.

## Explicitly deferred

- R3-4 bot-as-subject authority mode (S4) — S0b only lets a bot *create/lookup*.
- Party merge — the only remaining deferred Party correction; the operator-granted
  rename, add-document, contact-point deactivation and Party deactivation surfaces
  shipped as the S0b correction batch (`docs/v3/38` §4).
- Any inbound-message verification round-trip (verification codes) — S4 territory.

## R2 status (2026-09-01) - slices completed

- Attribution x platform (`source_kind`/`platform`, migration 0025) landed with
  provenance-based verification per `docs/v3/38` §9.2: patient contact points are
  created verified, no ceremony.
- Acting-operator relay (`platform.acting_for_operator`, `X-RE-Acting-Operator`) shipped;
  effective-actor authorization and idempotency scoping verified on PostgreSQL.
- Revision ledger + rollback landed: append-only `party_identity_revisions` with
  full-snapshot history, DB-rejected UPDATE/DELETE, rollback as a new revision.
- Staff verification slice landed: `staff.manage_own_admin_contact` and
  `staff.confirm_own_admin_contact` with hashed one-time code, expiry, attempt limit
  and outbox transactional intent (`staff.contact_verification_requested.v1`); the
  "verification codes - S4 territory" deferral above is superseded for staff
  administrative contacts only.
