# Tenancy module

Owns `Organization`, `Principal`, `Party`, and `Representation` semantics and local authority materialization.

Primary concerns: hard tenant boundary, authority snapshots/revocation coordination, actor/party distinction, and exact policy/representation provenance.

Other modules consume only public tenancy contracts; participant roles or external correlations never become authorization by implication.

## Private platform provisioning

`api/native_platform_provisioning.py` owns native provisioner and organization-root
creation transport; its typed application commands execute through the dedicated
platform-control DB connection. The separate HTTP entrypoint only composes that
supported API. See `docs/architecture/http-runtime-deployment.md` for operation
IDs, authentication, idempotency, privilege and transaction contracts. Native
enrollment alone still grants no Principal or tenant authority, and a provisioner
does not become a member of the tenant it creates.

Native organization creation selects the versioned initial controller policy
documented in `docs/architecture/initial-controller-policy.md`. Its explicit
grants and policy provenance are atomic with the root; replay never upgrades
legacy roots or restores revoked authority. New capabilities are not inherited
automatically from the runtime registry.

Agent provisioning returns separate profile and authority revision snapshots,
allowing initial authority assignment without database access. Idempotent replay
preserves the original revisions and omits the one-time credential; historical
responses without an authority revision return null. This is not a current-state
inspection API. Separate `agent_list` / `agent_get` reads expose current profile
and authority revisions plus standing capabilities under current HUMAN
`agent.read` authority. They do not expose credentials or claim effective access
to every Party/resource. See `docs/architecture/agent-governance-inspection.md`.

## Party registry (S0b)

Owns `parties.register`, `parties.add_contact_point`, `parties.confirm_contact_point`,
the operator-granted corrections (`parties.rename`, `parties.add_document`,
`parties.deactivate_contact_point`, `parties.deactivate`),
`parties.rollback_identity`, `parties.lookup` and `parties.read_revisions`
(contract: `docs/v3/38-s0b-party-registry-contract.md`, §9 for the R2
authority/platform model). A Party is identity-only — never a CRM profile.
Attribution records two orthogonal durable facts: `source_kind`
(`operator`/`subject` — whose authority produced the change, derived from the
effective principal's kind; an integration principal relayed through an
admitted acting operator attributes to the operator) and `platform` (declared
by the trusted layer, never an authorization input). Every contact point is
created verified (§9.2); the confirm command remains for secondhand
information paths and the DB guard rejects downward flips. Phone lookup is
multi-match by design (shared family numbers). Identity documents
(cédula/passport) are unique per tenant, kind and normalized value. Correction
capabilities are grant-gated operator-only; bots hold only
register/add_contact_point/lookup, and bot-created Parties get a
"WhatsApp <number>" placeholder name corrected via `parties.rename`. Every
party mutation appends one full-identity revision to the append-only
`party_identity_revisions` ledger in the same transaction (§9.3); rollback
applies a prior snapshot as a new revision while verification stays monotone.

## Business onboarding authority (docs/v3/44)

`organization.bootstrap` allows a freshly provisioned principal to establish
the tenant's root operational authority through
`POST /v1/organization/bootstrap-operational-authority`: it grants the four
`operations.manage_*` scopes as delegated Representations on an active
`organization` Party. It is bootstrap-only (idempotent replay, no general
Representation administration) and exposes the owner-backed
`has_active_organization_party` fact consumed by `GET /v1/onboarding/readiness`
(`onboarding.read` composes this fact through `contracts/onboarding_readiness.py`;
the readiness router is Tenancy-owned HTTP composition over other modules'
published readers).

## Staff administrative contacts (R2)

Staff (operator) principals register their OWN administrative contact
(`staff.manage_own_admin_contact`) and confirm it with a one-time 6-digit code
(`staff.confirm_own_admin_contact`; contract: `docs/v3/38` §9.2). RE owns the
durable intent: the code is stored only as a sha256 hash with a 15-minute
expiry and a 5-attempt limit, and ONE outbox event
(`staff.contact_verification_requested.v1`) carries the code verbatim as
transactional intent — delivery stays external (outbox → webhook transport →
WhatsApp). Verification is mandatory here, unlike patient contact points,
which are verified by provenance. `principal_id` is forced from the
authenticated actor; integration/relay callers get a typed 403. Replay of the
verification request never re-exposes a code, and the 0025 DB guard keeps
`verified` monotone even against direct SQL.
