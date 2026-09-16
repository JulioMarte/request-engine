# Authentication implementation: local validation checkpoint

Date: 2026-09-12. This is a verification checkpoint, not a replacement for the
acceptance criteria in `identity-provider-and-staff-provisioning-plan.md` or the
amended slices in `principal-agent-and-provisioning-authority-model.md`.

**Overall status: incomplete; not certified for production.** Passing the current
tests is necessary but does not prove the unimplemented acceptance journeys.

Detailed continuation plan: `auth-production-completion-plan.md` (2026-09-14).
It specifies implementation order, proposed operations, ownership, security
decision gates, transactions, proof matrix and operational exit criteria. Its
recovery/linking policy was accepted by ADR 0013 (2026-09-14) and activated in
revisions 0045-0051. The real secret store and delivery channel (Block C-02) are
implemented and production-wired; operational acceptance of the chosen environment
and secret manager remains under D6.

## Tenant staff/agent/integration append-only audit (B4) (2026-09-16, no new revision)

Block B4 of `auth-production-completion-plan.md`, under the frozen decision to reuse
the existing append-only `request_engine.audit_records` boundary rather than add a
new table or migration. Source-only change on branch `cohesion/system-optimization`;
head remains `0052_issuance_reservation` and `alembic heads` is one. Local
dirty-tree evidence only; no exact-head GitHub CI.

Production change:

- Each tenant staff, agent and integration identity command now commits exactly one
  append-only `request_engine.audit_records` row inside its existing
  `actor_transaction`, after the authoritative SQL mutation and the idempotency
  close, via `request_engine.platform.audit.postgres.append_audit`. No new lock, no
  network I/O and no privilege/topology change: the app role already holds
  `SELECT,INSERT`, the tenant RLS `WITH CHECK` and the append-only trigger.
- Typed, secret-free detail schema in
  `modules/tenancy/application/commands/identity_audit.py`
  (`IdentityAuditAction`, `IdentityAuditReason`, `IdentitySubjectKind`, and the
  bounded `IdentityAuditDetails` dataclass). Adapters write it through the thin
  tenancy-local `modules/tenancy/adapters/db/identity_audit.py` helper, which keeps
  `aggregate_kind` equal to `subject_kind`.
- `command_name` is the stable capability/operation identifier (`staff.invite`,
  `staff.manage_authority`, `staff.manage_membership`, `agent.provision`,
  `agent.manage_authority`, `agent.suspend`, `integration.provision`,
  `integration.manage_authority`, `integration.transition_status`,
  `integration_credential_rotate`). `aggregate_kind` is `StaffMembership`,
  `AgentPrincipal`, `IntegrationPrincipal` or `IntegrationCredential`.
- Replay never audits: the early replay branch returns before the audit append, so
  one effect yields one row. A rejected command or any rollback leaves zero rows.
- `integration_governance_facts` is preserved byte-for-byte as the integration
  provenance snapshot; the new `audit_records` row is the uniform cross-family audit
  record. Both are written in the same transaction for integration commands.

Executed evidence (real PostgreSQL 18.6, `request_engine_current` at 0052):

- `tests/db/test_identity_governance_audit.py` (5 proofs): for each family, exactly
  one audit row per command with actor, aggregate kind/id, action, reason and real
  before/after revisions, checked against the independently read aggregate state;
  replay leaves one row; rejected stale commands leave none; a foreign tenant cannot
  see the row (RLS); the runtime app role gets `42501` on `UPDATE`/`DELETE`; the
  rotate details contain no token, digest or secret.
- `tests/unit/test_identity_audit_details.py` (8 proofs): typed detail schema,
  optional/normalized `external_case_reference`, bounded revisions and closed
  reason codes.
- Mutation check: deleting the `staff.invite` audit append turned the DB proof red
  (`got 0`); auditing the replay path instead turned it red (`got 2`); restoring the
  code restored green.
- Extended e2e journeys `tests/e2e/test_native_staff_lifecycle.py`,
  `test_native_agent_lifecycle.py` and `test_native_integration_lifecycle.py` now
  assert a durable audit row after a real HTTP command plus replay, and the rotate
  journey additionally asserts the uniform audit row is secret-free.
- New guarantee `INV-TENANT-IDENTITY-AUDIT-001` with proof-map entries; the new DB
  suite was added to `scripts/ci/run_current_product.sh`.

Decisions and honest limits:

- `reason_code` is operation-derived (a closed enum), because the current tenant
  command contracts do not carry an operator-supplied reason. Adding an operator
  reason field would change the HTTP/application contracts and is not part of B4.
- `external_case_reference` is part of the typed schema but is always absent today
  for the same reason; it is unit-tested at the schema boundary.
- For creation commands (`invite`/`provision`) `revision_before` is `0` and
  `revision_after` is the new aggregate revision (`1` for a fresh staff membership
  or agent profile, the returned authority revision for integration). For
  transitions and rotations `revision_before` is the caller's expected revision and
  `revision_after` is the revision PostgreSQL returned.
- For `integration_credential_rotate` the aggregate is the new
  `IntegrationCredential` and the before/after revisions describe the parent
  integration Principal's authority revision that the rotation bumped.
- Platform-plane commands, binding lifecycle, and `identity_exchange`/party commands
  (which already audited) are out of B4 scope and unchanged.
- No commit, push, PR, deployment or application-database migration; evidence is
  local/dirty-tree only.

## Real recovery secret delivery adapter (C-02) and issuance-discard fix (2026-09-16)

Block C-02 of `auth-production-completion-plan.md` under the D2/D6 owner decisions
(Vault KV v2 secret store; SMTP delivery channel, Mailu-compatible, with a
`module:factory` seam for a future WhatsApp channel). No new migration; source-only
composition change on branch `cohesion/system-optimization`. Local evidence only;
exact-head CI for this change has not yet run.

Production change:

- `platform/secrets/vault_secret_store.py` (`VaultRecoverySecretStore`) stages the
  raw proof in Vault KV v2 create-if-absent (`options.cas=0`), reads it back only
  for publication, and treats a CAS conflict by returning the retained secret with
  `created=False` instead of overwriting. `platform/secrets/smtp_delivery_channel.py`
  (`SmtpRecoveryDeliveryChannel`) publishes over SMTP with a deterministic
  hashed `Message-ID`; `platform/secrets/composed_delivery.py`
  (`ComposedRecoverySecretDelivery`) composes store + channel and satisfies the
  existing `RecoverySecretDelivery` port. `StagedRecoverySecret` gained a required
  `created` flag.
- `bootstrap/recovery_delivery.py` resolves the adapter from explicit
  `REQUEST_ENGINE_VAULT_*` / `REQUEST_ENGINE_SMTP_*` / `REQUEST_ENGINE_RECOVERY_*`
  configuration or a `REQUEST_ENGINE_RECOVERY_DELIVERY_FACTORY=module:factory`
  override. A partial configuration fails startup; an absent configuration returns
  `None` and keeps issuance fail-closed (`503 recovery_delivery_unconfigured`).
  `bootstrap/platform_server.py` passes the adapter to the private control plane and
  `bootstrap/reference_worker_factory.py` composes the fenced delivery stream into
  the production worker.
- Two defects fixed: (1) `_discard_staged` in `identity_recovery_commands.py` now
  no-ops when the staged secret was not created by this call, so a concurrent
  issuance that lost create-if-absent no longer deletes the retained secret; (2) the
  SMTP `Message-ID` was derived from the raw `case:generation` key, which stdlib
  `email` truncated at the colon; it is now a sha256 hash of the key.

Executed evidence (real PostgreSQL 18.6, `request_engine_current` at 0051):

- `tests/unit/platform/secrets/` (31 unit proofs): Vault CAS/conflict/discard/read/
  expiry/error mapping; SMTP outcome mapping and hashed `Message-ID`; composite
  delegation.
- `tests/modules/platform/test_recovery_delivery_assembly.py` +
  `test_worker_production_assembly.py`: fail-closed config resolution and worker
  stream wiring.
- `tests/e2e/test_native_identity_recovery_http.py`: now 8 proofs, including 4
  real-adapter journeys (`test_identity_recovery_delivery`,
  `_ambiguous_delivery_is_not_blindly_retried`,
  `_connection_failure_is_safely_retried`, `_invalid_destination_is_permanent`)
  against a Vault KV v2 HTTP double and an SMTP transport double, with real
  DB/worker/HTTP.
- `tests/db/test_identity_recovery_governance.py`: now 10 proofs, including
  `test_concurrent_issuance_keeps_the_retained_secret`, whose mutation check (guard
  removed) turned red and restored green.
- `python-quality`: 12/12 PASS.

Honest limits:

- Real Vault and real SMTP servers were not exercised; the evidence uses boundary
  doubles at the external Vault/SMTP boundary. Provider/delivery certification
  remains G/D6.
- **Residual concurrency hole (closed by revision 0052):** the C-02 fix covered
  only the issuance that lost create-if-absent. A concurrent issuance that
  *created* the staged secret but lost the authoritative transaction could still
  discard the secret the winner's ticket references. The plan's remedy —
  generation reservation before staging — is implemented by
  `0052_issuance_reservation`; see the next section.
- SMTP has no reconciliation query surface, so an ambiguous post-transmission
  outcome is recorded `unknown` and not republished; only a pre-transmission
  connection failure is retried.
- No WhatsApp/OIDC delivery channel is implemented; the factory seam is the only
  extension point. No OIDC or app-database migration, commit, push, PR or deployment
  was performed for this block.

## Recovery issuance generation reservation (2026-09-16, revision 0052)

Revision `0052_issuance_reservation` (file
`migrations/versions/0052_identity_recovery_issuance_reservation.py`) appends from
`0051` and implements the section C2 remedy: the issuance generation is reserved
per attempt before the raw proof is staged.

Production change:

- New private table `request_engine.identity_recovery_issuance_reservations`
  (`PRIMARY KEY (case_id, generation)`, `UNIQUE (case_id, idempotency_key_digest)`,
  generation and digest checks). Owner `request_engine_schema_owner`; no runtime
  role access. The control definer receives column `SELECT`/`INSERT` on
  `(case_id, generation, idempotency_key_digest)` and a table-level `DELETE`.
- `request_platform.prepare_identity_recovery_issue` reuses the reservation for an
  already-reserved idempotency key or inserts `max(live reservation, committed
  generation) + 1` under the existing `FOR UPDATE` case lock, then returns that
  reserved generation in the `issuance_generation` column. The idempotency replay
  path still returns the committed case view.
- `request_platform.issue_identity_recovery_case` accepts only the exact
  `(case_id, generation, idempotency_key_digest)` reservation at both generation
  gates, and deletes the reservation in the same transaction that marks the case
  `issued`.
- `identity_recovery_commands.issue_case` stages the generation `prepare`
  returned instead of adding one.

Consequence: two concurrent issuances of one case reserve and stage distinct
generations, so the authoritative loser discards only its own staged generation;
the retained secret the winner's delivery ticket references is never deleted. The
previous create-if-absent guard remains necessary but is no longer the only
protection.

Executed evidence (real PostgreSQL 18.6, `request_engine_current` at 0052):

- `tests/db/test_identity_recovery_governance.py` (11 proofs): direct flows thread
  one idempotency key and the reserved generation from prepare into issue; the
  happy path asserts the reserved generation 1; a new proof asserts two keys
  reserve generations 1 and 2, re-preparing a key reuses its reservation, and an
  unreserved generation is rejected `40001`; the concurrency proof is rewritten so
  the two issuances reserve distinct generations and the loser discards only its
  own. Mutation check: reverting both functions to the pre-0052 bodies turned the
  concurrency proof red at "the winning staged secret was deleted by the losing
  issuance"; restoring turned it green.
- `tests/db/test_platform_control_definer_topology.py`,
  `tests/db/test_platform_definer_topology.py`,
  `tests/db/test_runtime_immutable_table_privileges.py`,
  `tests/db/test_v3_runtime_privilege_contract.py` and
  `tests/db/runtime_table_contract.py` updated for the new private table and the
  definer's reviewed `SELECT`/`INSERT` columns plus the table-level `DELETE`.
- `tests/e2e/test_native_identity_recovery_http.py`: 8 proofs pass; a first
  issuance is still generation 1.
- `python-quality`: 12/12 PASS.

Honest limits: local evidence only; GitHub exact-head CI for 0052 has not run.
The reservation table-level `DELETE` is a deliberate widening of the control
definer's reviewed surface (PostgreSQL has no column-level `DELETE`).

## OIDC identity linking and link hardening (2026-09-16, revisions 0050-0051)

Revisions `0050_identity_link_hardening` and `0051_oidc_identity_link` append from
`0049` (chain `...0047 -> 0048 -> 0049 -> 0050 -> 0051`; current Alembic head is
`0051`). GitHub exact-head CI is green for this chain at branch head `4d873ec7`
(run [35121436765](https://github.com/JulioMarte/request-engine/actions/runs/35121436765),
5/5 required jobs, 13m37s); the branch is not merged or deployed. This section
extends and supersedes the "native-only / OIDC out of scope" statement in the
0048-0049 section below.

Production change:

- 0050 hardens self-service linking and native session activity. Continuity refusal
  now surfaces as SQLSTATE `55000` (a mapped conflict) instead of `23514` (a mapped
  input error). A partial unique index `identity_link_intents_live_uq` permits at
  most one live pending intent per organization+actor+authority;
  `create_identity_link_intent` expires stale pending intents before its existence
  check, and a tenant-scoped `request_engine.read_identity_link_intent` reader lets
  the confirm boundary derive the target authority from trusted persisted state
  rather than a body-supplied hint. `request_auth.touch_native_session` records
  bounded session activity without exposing native session tables to the app role.
- 0051 adds the OIDC second-proof path. `request_engine.confirm_identity_link_subject`
  mirrors the native confirmation exactly (same identity-topology gate, ordered
  staff root, actor/intent revalidation, consume-once semantics) but locks the
  intent's authority `FOR SHARE`, rejects a `native` authority, conflicts when the
  subject is already linked in the tenant, and creates the binding for the SAME
  tenant Principal. Native confirmation keeps its own primitive; the two are
  distinct.
- `platform/security/oidc_link.py` composes `OidcIdentityLinkVerifier`/`OidcLinkVerifier`
  over live persisted authority configuration; the target authority is always the
  intent's, never a request-body hint. `modules/tenancy/api/identity_link_routes.py`
  adds `OidcIdentityLinkProofBody` and calls `oidc_verifier.verify`; a deployment
  without a composed verifier fails closed with 403 `identity_link_not_configured`.
  `adapters/db/identity_link_commands.py` dispatches to `_CONFIRM_SUBJECT_SQL`.

Real versus mocked OIDC verification:

- Verification is real: `platform/security/oidc_auth.py` implements RFC 9068
  (`typ=at+jwt`) resource-server tokens signed with RS256 against the authority's
  JWKS (`HttpxJwksFetcher`, `OidcTokenAuthenticator`). There is no token
  introspection endpoint. Only the JWKS HTTP transport is mocked in tests.

Executed evidence (real PostgreSQL 18, `request_engine_current` at 0051):

- `tests/db/test_identity_link_hardening.py` (0050) and
  `tests/db/test_identity_link_subject.py` (0051).
- `tests/e2e/test_identity_link_self_oidc_http.py` (real RSA/RS256-minted tokens;
  only the JWKS HTTP transport is mocked).
- `tests/db/test_native_multi_session.py`, `tests/unit/platform/security/test_native_session.py`
  and `tests/unit/platform/security/test_step_up_enforcement.py`.

Honest limits:

- OIDC remains OPTIONAL and disabled by default: `oidc_enabled=False`
  (`REQUEST_ENGINE_OIDC_ENABLED`), and no OIDC identity_authorities row is seeded.
  A deployment without a composed verifier fails closed.
- No introspection means external revocation cannot be observed instantly; the
  verifier re-reads the live authority config before and after the network call,
  but upstream token revocation is not polled.
- `deploy/authentik/` is a manual/opt-in real-provider stack; CI never starts it,
  so CI does not exercise a live external IdP.
- `INV-IDENTITY-LINK-SELF-001` (including its OIDC clause) and
  `INV-NATIVE-MULTI-SESSION-001` in `testing/current-guarantees.toml`, and the
  matching entries in `testing/current-proof-map.toml`, already reflect this state.

## Self-service identity linking and reauthentication freshness (2026-09-16, revisions 0048-0049)

Block D2 of `auth-production-completion-plan.md` (native-only at the time; superseded
by revisions 0050-0051, see the newest section) under ADR 0013 D3/D4.
Migrations `0048_native_reauth_freshness` and `0049_identity_link_self` append from
`0047`. Local/dirty-tree evidence only; no exact-head CI.

Production change:

- 0048 adds `native_sessions.last_authenticated_at` as the auth_time freshness basis
  (backfilled from `created_at`), re-emits the session guard for monotonic updates,
  extends `request_auth.read_native_session` and the trusted `NativeSessionSnapshot`
  with `created_at`/`last_seen_at`/`last_authenticated_at`, threads `authenticated_at`
  through `ActorContext`, and adds the private `POST /auth/native/sessions:reauth`
  step-up plus the ADR-0013 five-minute `require_recent_authentication` guard.
- 0049 adds the `identity.link_self` capability, short-TTL nonce-bound
  `identity_link_intents`, and an exactly-once confirm that creates a tenant identity
  binding for the caller's existing Principal after proving a second native identity
  outside authoritative locks. Both endpoints require a recent reauthentication and
  refuse delegation, administrative linking, grants, membership changes and Principal
  merges. A subject already linked to any Principal conflicts, foreign intents are
  opaque, and `identity_link_facts` audits intent creation and linkage.
- OIDC linking is intentionally out of scope: no OIDC connection exists, so the
  dual-proof scheme is native-only for now. (Superseded by revisions 0050-0051: see
  the OIDC identity linking and link hardening section.)

Executed evidence (real PostgreSQL 18, `request_engine_current` at 0049):

- `tests/db/test_native_reauth_freshness.py`, `tests/e2e/test_native_session_reauth_http.py`,
  `tests/db/test_identity_link_self.py`, `tests/e2e/test_identity_link_self_http.py` and
  `tests/e2e/test_native_identity_global_disable_http.py` pass.
- `python-quality` 12/12; `tests/db -m postgres` 443 passed; `tests/e2e -m postgres`
  421 passed with 2 pre-existing order-dependent failures (`test_live_queue_privacy`,
  `test_world_business_timezone`) that pass in isolation.
- Found and fixed a regression introduced by revision 0047: `_verify_login` embedded
  the now-tuple `_LIFECYCLE` as a single entry; corrected to spread it.

## Governed native identity global disable (2026-09-15, revision 0047)

Block D3 of `auth-production-completion-plan.md` under ADR 0013 D5. Migration
`0047_native_identity_disable` appends from `0046`. Local/dirty-tree evidence only;
no exact-head CI.

Production change:

- New private platform reader `GET /v1/platform/native-identities` /
  `{native_identity_id}` (`platform_native_identity_list` / `_get`) under
  `platform.identity.read`, and `POST .../{native_identity_id}:disable`
  (`platform_native_identity_disable`) under new capability
  `platform.identity.disable`. Mounted only on `create_platform_control_app`.
- `request_platform.disable_native_identity` takes the identity-topology gate
  EXCLUSIVE with a bounded `lock_timeout` (10s containment), revalidates the
  platform actor and grant, disables the native identity terminally and revokes
  credentials, sessions and pending recovery intents, then proves every affected
  tenant and the platform plane retain an effective controller. Bindings, grants
  and provenance are preserved as historical facts; the identity is never
  re-enabled. A `platform_identity_disable_facts` append-only table records the
  actor, revisions, reason and idempotency digests.
- Existing platform controllers receive the bootstrap grant; new roots still need
  the E1 controller-policy upgrade ceremony.

Executed evidence (real PostgreSQL 18, `request_engine_current` at 0047):

- `tests/db/test_native_identity_global_disable.py` (3 proofs): terminal disable +
  credential revocation + idempotent replay, refusal to remove the last tenant
  controller (atomic rollback), platform authority and stale-revision rejection.
- Deterministic definer-privilege inventories updated coherently
  (`test_platform_definer_topology.py`, `test_platform_control_definer_topology.py`,
  `test_runtime_immutable_table_privileges.py`).

Honest limits:

- No private HTTP journey proof yet for the D3 routes; the DB command and route
  registration are validated, but the end-to-end platform HTTP test is pending.
- The EXCLUSIVE containment is a fixed 10s `lock_timeout`; production contention
  limits remain a D6 operational decision.
- No append-only audit beyond the disable fact table; B4 for tenant staff/agent/
  integration commands is still absent.

## Identity binding lifecycle and inversion-free staff lock order (2026-09-15, revision 0046)

Block D1b of `auth-production-completion-plan.md`, under the D4/D5 decisions
ratified by ADR 0013. Branch `cohesion/system-optimization`; source dirty;
local/dirty-tree evidence only. Migration `0046_identity_binding_lifecycle`
appends from head `0045`; the accepted baseline is untouched.

Production change:

- New tenant-control command surface `POST /v1/identity-bindings/{binding_id}:suspend`,
  `:reactivate`, `:revoke` (`identity_binding_suspend` / `identity_binding_reactivate`
  / `identity_binding_revoke`) behind the existing `identity.bind` capability, which
  is now a runtime OPERATOR `RevisionPolicy.REQUIRED` command (previously INTERNAL
  and non-runtime). HUMAN-only, `expected_revision`, `Idempotency-Key`, `no-store`.
- `request_engine.transition_identity_binding` (SECURITY DEFINER, gate SHARE first)
  validates the transition, increments the binding revision exactly once, keeps
  revoke terminal and revalidates tenant controller continuity.
- Lock-order fix: new `request_engine.lock_tenant_staff_root` acquires the ordered
  active-staff-membership root before any specific row. `transition_staff_membership`
  and `replace_staff_authority` now call it immediately after the topology gate,
  removing the specific-row-before-root inversion that could abort two mutually
  targeted transitions with `40P01`. New `request_engine.assert_tenant_has_controller`
  supports the binding continuity check without excluding the affected principal.
- Files: `application/commands/identity_binding.py`,
  `adapters/db/identity_binding_commands.py`, extended
  `api/identity_binding_routes.py`, wiring in `modules/tenancy/api/__init__.py`,
  capability definition in `platform/security/capability_registry_identity_authority.py`.

Executed evidence (real PostgreSQL18, dedicated `request_engine_current` at0046):

- `tests/db/test_identity_binding_lifecycle.py` (4 proofs): revision/idempotency,
  terminal revoke, stale revision, last-controller continuity, tenant scope, no
  authority grant, non-HUMAN and unprivileged denial, gate-first ordering.
- `tests/e2e/test_identity_binding_lifecycle_http.py` (1 journey): 403 without the
  standing grant, mandatory Idempotency-Key, suspend/reactivate/revoke over HTTP,
  terminal/stale conflicts, foreign/random 404 with identical bodies, no-store.
- `tests/db/test_identity_topology_races.py` (3 proofs): deterministic root-before-
  specific ordering for both staff and binding writers, and a mutual binding
  suspension that resolves without `40P01` and retains a controller. The existing
  mutual staff suspension proof now rejects `40P01` explicitly.
- New guarantee `INV-IDENTITY-BINDING-LIFECYCLE-001`; proof-map and current-product
  selection updated. `python-quality` 12/12 PASS (local).

Deliberately NOT changed and honest limits:

- D2 self-service dual-proof linking, D3 global native disable and the private
  native-identity reader remain unimplemented; `platform.identity.disable` is still
  unregistered.
- B4 append-only audit for tenant staff/agent/integration commands is still absent;
  the binding lifecycle writes no append-only audit fact either.
- The binding lifecycle is tenant-local: it does not revoke a shared native
  identity's sessions globally, and it grants or restores no authority.
- No commit, push, PR, deployment or application-database migration. Evidence is
  local/dirty-tree only; no exact-head CI.

## Identity binding read projection (2026-09-15, no new revision)

First step of Block D of `auth-production-completion-plan.md`. Branch
`cohesion/system-optimization`; source dirty; local/dirty-tree evidence only. No
migration was added; the accepted head remains `0045_identity_recovery_case`.

Production change:

- New tenant-control query capability `identity.binding.read`. New tenancy-owned
  HTTP surface `GET /v1/identity-bindings` (`identity_binding_list`) and
  `GET /v1/identity-bindings/{binding_id}` (`identity_binding_get`), mounted on the
  tenant app with `no-store`. The projection exposes binding id, principal id,
  authority id, status, revision and creation time only: never `subject_id`, a
  verifier, a token or another tenant's row.
- `modules/tenancy/api/identity_binding_routes.py` (transport and bounded error
  mapping), `application/queries/identity_binding.py` (view, queries, errors) and
  `adapters/db/identity_binding_admin_reader.py` (single-snapshot authorization and
  row read under `actor_transaction` and tenant RLS). Authorization is the actor's
  current `identity.binding.read` standing grant; a forged in-memory capability
  alone is denied.

Executed evidence (real PostgreSQL18.6, dedicated `request_engine_current` at0045):

- `tests/db/test_identity_binding_reads.py` (2 proofs): authority required and
  revocation closes the surface, non-HUMAN rejected, tenant opacity (foreign and
  random bindings both 404 with an identical body and are never listed), no
  `subject_id` exposure, mutation-free reads against an independent SQL oracle,
  bounded filters and cursor, invalid status/limit rejected.
- `tests/e2e/test_identity_binding_reads_http.py` (1 journey): native login,403
  before the grant,200 with `no-store` after, exact field set, detail200, foreign
  and random404 with identical bodies, invalid filter422, mutation-free fingerprint.
- New guarantee `INV-IDENTITY-BINDING-READ-001` with proof-map entries. Both new
  files were added to `scripts/ci/run_current_product.sh`, and the two operations
  were classified in the e2e public-surface registry.
- `python-quality`: 12/12 PASS (`.ci/python-quality-verify-binding-read.json`,
  logs `.ci/logs-verify-binding-read/`).
- Consolidated touched-surface selection (the two new files plus
  `test_identity_bindings`, `test_identity_topology_gate`,
  `test_staff_membership_lifecycle`, `test_self_authority_reader`,
  `test_public_surface_contract`, `test_http_security_matrix`):109 passed,
  0 failures (`.ci/identity-binding-read.xml`).

Deliberately NOT changed and honest limits:

- Binding lifecycle commands (`identity_binding_suspend`/`_reactivate`/`_revoke`)
  are NOT implemented. They are topology writers and would need the identity-topology
  gate (SHARE) plus controller-continuity revalidation. That revalidation serializes
  on the tenant staff-membership lock root, while `transition_staff_membership`
  acquires a specific membership before that root; a binding-first writer can
  therefore invert lock order and race two last-path revocations. Implementing it
  safely requires an explicit lock-order protocol and the B-02 race proof the plan
  already requires. I did not fake it with an EXCLUSIVE gate (reserved by ADR 0013
  for global operations) nor by dropping continuity. `identity.bind` remains
  INTERNAL and non-runtime.
- The projection omits `authority_kind` ("subject class") because the app role has no
  `SELECT` on `request_engine.identity_authorities`; adding it needs a reviewed
  runtime privilege widening or a definer read.
- B4 append-only audit for tenant staff/agent/integration commands is still absent;
  this read-only surface adds no command, so B4 is unchanged.
- D2 linking, D3 global disable and the private native-identity reader remain
  unimplemented; `platform.identity.disable` is still unregistered.
- No commit, push, PR, deployment or application-database migration. `request_engine`
  (app DB) remains empty in the recreated volume; `request_engine_current` is at0045.
- One observed nuance: the pre-grant HTTP denial is403 from the generic
  `require_capability` gate (code `capability_required`), not the operation-specific
  `identity_binding_forbidden`, which only surfaces when the in-memory capability is
  present but the standing grant is absent, or the actor is non-HUMAN.

Next block: B4 append-only audit for tenant staff/agent/integration commands, then
the E blocks (E1 controller-policy upgrade, E2 onboarding readiness, E3
resource-effective authority inspection), followed by F adversarial journeys and G
operational acceptance.

## Governed identity recovery implementation and validation (2026-09-15, revision 0045)

Block C of `auth-production-completion-plan.md` was implemented under the D1/D2
policy ratified by ADR 0013 and locally validated in this session. Branch
`cohesion/system-optimization`; `origin/development` was fetched and is0
ahead/326 behind; the integration lane matches. Source is dirty; none of this is
exact-head GitHub evidence. PostgreSQL18.6.

Production change (revision `0045_identity_recovery_case`):

- Tenancy owns `request_engine.identity_recovery_cases`
  (`requested -> approved -> issued -> consumed / revoked`) with a structural
  `approver <> requester` constraint, bounded evidence/destination references,
  a monotonic revision and captured approval/proof expiries. Approval expires
  after24 hours; issuance proofs are bounded to the30-minute default. Expiry is
  evaluated as a predicate at command time, like native recovery intents; no
  authoritative `expired` state is invented.
- `request_engine.identity_recovery_delivery_tickets` holds one opaque secret
  reference, its fingerprint, the destination snapshot and the lease/fence per
  issuance generation. `request_engine.platform_identity_recovery_facts` is a
  private append-only audit boundary (request/approve/issue/revoke/consume/
  deliver/delivery_unknown/delivery_failed) with no runtime table access.
- The five private commands take the identity-topology gate as their first
  statement (SHARE) and revalidate the current actor authority revision and
  grant before replay or write. Issuance supersedes every other live proof of
  the same native identity (case revoked, ticket cancelled, prior intents
  revoked by the auth primitive) in one transaction.
- Issuance is a saga: `prepare` returns the next generation, the raw proof is
  staged outside locks through the technical `RecoverySecretDelivery` port
  (create-if-absent per case+generation, TTL), and the authoritative transaction
  creates the recovery intent through
  `request_auth.create_native_recovery_intent` (which owns the authority SHARE
  and identity `FOR UPDATE` locks), links the case, creates the ticket and
  writes the fact. A rollback discards the staged candidate best-effort.
- Delivery is a fenced `FencedWorkerRuntime` stream over the ticket lease
  surface (`claim/complete/retry_after/dead_letter/renew`). The worker
  reconciles before republishing an ambiguous attempt and never publishes inside
  the issuance transaction. Consumption is linked to the case in the same
  transaction as `request_auth.consume_native_recovery_intent`.
- Private control-plane HTTP: `POST/GET /v1/platform/identity-recovery-cases`,
  `GET /{case_id}`, `POST /{case_id}:approve|issue|revoke` with stable
  operationIds, `Idempotency-Key`, `expected_revision`, `no-store` and bounded
  error mappings. New capabilities `platform.identity.read` and
  `platform.identity.recovery_approve`; `platform.identity.recover` became a
  runtime AUTHORITY_CHANGE command. All three are in the root trust set and were
  backfilled to existing platform controllers holding
  `platform.tenant_provisioner.provision`.
- Only the token digest/fingerprint, the secret-store reference and its
  fingerprint are persisted; the raw proof never enters PostgreSQL, audit facts,
  ordinary outbox or administrative responses.

Executed evidence (real PostgreSQL18.6, dedicated test database at0045):

- `tests/db/test_identity_recovery_governance.py` (9 proofs): happy path
  (create/approve/issue/replay/claim/deliver/consume) with durable state,
  credential replacement and a no-raw-secret sweep; requester-cannot-approve
  even with both capabilities; idempotent replay and key-reuse conflict; revoke
  kills intent, ticket and consumption; new issuance supersedes a prior live
  proof; lease fencing, retry and terminal failure; approval expiry and stale
  revision rejection; app/worker runtime denial; topology-gate-first structural
  proof for the five commands.
- `tests/e2e/test_native_identity_recovery_http.py` (4 journeys): full private
  HTTP journey with a test delivery adapter and the real worker runtime
  (201/403/200/202, replay, worker delivery, public consumption204, old password
  rejected, new password accepted); revoke terminates a staged proof; issue
  without a configured adapter fails closed with503; unbound callers and unknown
  cases are rejected opaquely and the six operationIds are published.
- `tests/modules/platform/test_recovery_delivery_worker.py` (19 unit cases):
  reconcile-before-republish ordering, outcome mapping, retryable/permanent
  failure propagation, fence-loss handling, idempotency key and store input
  bounds.
- Definer/privilege inventories were updated deliberately for the new reviewed
  surfaces: `test_platform_definer_topology`,
  `test_platform_control_definer_topology`,
  `test_runtime_immutable_table_privileges`,
  `test_platform_root_bootstrap_consume` and
  `test_native_identity_actor_runtime` (the root trust set now has8 grants).
- `python-quality`: **12/12 PASS** (`.ci/python-quality-block-c.json`, logs
  `.ci/logs-block-c/`).
- Full `scripts/ci/run_current_product.sh` on PostgreSQL18.6: **879 tests,0
  failures/errors/skips,18 JUnit reports, proof-map gaps empty**; accepted
  baseline integrity and populated multi-database upgrade through0045 passed
  (`.ci/current-product-block-c/`).

Two defects found and fixed during validation: the private-runtime factory
compared `regprocedure` text against permitted signatures containing spaces
(and `timestamptz` instead of `timestamp with time zone`), so the production
readiness check rejected its own new functions; and one stale capability-set
expectation in `test_native_identity_actor_runtime`. A first full-runner attempt
failed in the E2E group on those defects; the same artifact directory was
overwritten by the green rerun, so the failed attempt is recorded here rather
than retained as a separate artifact.

Honest limits:

- No production secret store or delivery adapter exists yet. The private control
  plane fails closed (`503 recovery_delivery_unconfigured`) until D6 names one;
  the in-test adapter only proves the port contract, not real delivery.
- `platform.identity.disable` (global disable), identity linking and the
  resource-authority inspection query remain unimplemented (D/E3).
- Tenant staff/agent/integration identity commands still lack append-only audit
  facts; B4 remains partial for those command families. Only the recovery case
  commands carry the B4 audit/idempotency semantics added here.
- The delivery worker is not wired into a production entrypoint: the bootstrap
  seam and stream composition exist and are proven with a test adapter, but the
  deployment process remains a D6 decision.
- This session's evidence is local/dirty-tree; exact-head GitHub CI remains the
  merge authority. No commit, push, PR, deployment or application-database
  migration was performed.

## Native enrollment outcome implementation and validation (2026-09-14, revision 0041)

Block A of `auth-production-completion-plan.md` was implemented and locally
validated in this session. Production change: `request_auth.create_native_identity`
now distinguishes `true=created`, `false=duplicate login handle` and
`NULL=authority absent/disabled/wrong kind`. The adapter returns a typed
`NativeEnrollmentOutcome` instead of collapsing the scalar through `bool()`; an
unexpected scalar raises `NativeEnrollmentOutcomeInvalid` as a closed internal
failure. The service maps duplicate and unavailable to distinct typed errors. HTTP
keeps201/409/422 and adds503 `native_enrollment_unavailable`
(`resolution=operator_intervention`, `retryable=false`, `no-store`/`no-cache`,
generic message, no login suggestion). Rejection creates no identity/credential
rows. The route's operationId, schemas and non-tool projection are unchanged.

Migration0041 preserves the function signature, owner `request_engine_schema_owner`,
`SECURITY DEFINER`, pinned `search_path`, `request_engine_app` EXECUTE without
PUBLIC EXECUTE, and the0040 authority `FOR SHARE` gate. It was applied only to the
dedicated test database `request_engine_current`; the Compose application database
`request_engine` remains0037. No0001–0040 revision was edited.

Branch `cohesion/system-optimization`; `origin/development` was fetched and is0
behind/326 ahead; the integration lane matches. Source is dirty; none of this is
exact-head GitHub evidence. PostgreSQL18.6.

Executed evidence:

- Focused unit selection (enrollment transport and service):20 passed.
- DB proofs: `tests/db/test_native_enrollment_outcomes.py` (new; exact trivalent
  scalars through the app role), `test_native_authority_suspension.py` (service maps
  unavailable, unknown/wrong-kind direct calls return `NULL`) and
  `test_native_authority_suspension_locks.py` (committed-suspension enrollment loser
  must read `NULL`, not duplicate): **39 passed in99.09s**
  (`.ci/block-a-db.xml`).
- E2E `test_native_authority_suspension_http.py` + `test_native_enrollment.py`:
  suspended, absent and wrong-kind authority all return503; duplicate remains409;
  no rows created: **5 passed** (`.ci/block-a-e2e.xml`).
- Falsifiability: in scratch database `request_engine_enrollment_mutant` on the
  isolated cluster (127.0.0.1:55689), restoring the0040 function body made
  `test_unavailable_authority_is_not_a_duplicate_sql_outcome`,
  `test_service_maps_duplicate_and_unavailable_to_distinct_errors` and all three
  unavailable-authority HTTP cases fail by observing409/duplicate (**5 failed, 2
  passed**, `.ci/block-a-mutant.xml`). Re-applying the0041 body made the same
  selection pass (**7 passed**, `.ci/block-a-mutant-restored.xml`). The mutant was
  applied and restored by exact SQL in scratch; the canonical database was not
  mutated.
- `python-quality`: **12/12 PASS** (`.ci/python-quality-block-a.json`, logs
  `.ci/logs-block-a/`), including180 architecture, unit and module suites. One
  pre-existing Starlette TestClient deprecation warning remains; no dependency
  changed.
- Full `scripts/ci/run_current_product.sh` on the isolated PostgreSQL18.6 cluster:
  **821 tests, 0 failures/errors/skips, 18 JUnit reports, 301 executed test files,
  proof-map gaps empty**; accepted baseline integrity and populated multi-database
  upgrade through0041 passed. E2E:412 passed, 2 deselected. Artifacts:
  `.ci/current-product-block-a/`.

Decisions: none of D1–D6 was assumed or activated. No capability, tool audience,
recovery issuance, linking or global identity administration changed.

Not done: no commit/push/PR/merge, no application-database migration, no
deployment, no Linux/Python3.13 repetition for this block, and no exact-source
`quality-evidence/v2` packets for the dirty tree.

## Tenant controller continuity implementation and validation (2026-09-14, revision 0042)

The ratified D4 policy was applied to the tenant plane. Migration0042 adds
`request_engine.principal_is_effective_tenant_controller(organization, principal)`
and replaces `assert_other_tenant_controller` to use it, so the authoritative
last-controller check no longer counts a grant-only membership. An effective
controller requires an active tenant Principal, an active membership, the current
three control grants (`staff.manage_membership`, `staff.manage_authority`,
`identity.bind`) and at least one active binding to an active identity authority.
For native subjects the bound identity and its active password credential must
exist; an active `oidc` authority counts as a configured external authenticator
without promising network availability or upstream token revocation. The predicate
runs inside the same command transaction and keeps the previous membership lock
order. The helper is schema-owner definer, PUBLIC EXECUTE revoked and not exposed
to app/worker roles. No capability, route or tool changed.

Executed evidence (PostgreSQL18.6, dedicated test DB):

- Five new DB proofs in `tests/db/test_staff_membership_lifecycle.py`: four
  independent path breaks (binding revoked, credential revoked, identity disabled,
  authority disabled) each deny removing the last controller with SQLSTATE23514
  and leave the target membership active; one positive proof shows a configured
  OIDC binding preserves continuity after the native path is retired.
- Principal-authority DB block: **147 passed** (`.ci/block-b2-principal-authority.xml`).
- Focused E2E staff/agent/provisioning journeys: **6 passed**
  (`.ci/block-b2-e2e.xml`).
- `python-quality`: **12/12 PASS** (`.ci/python-quality-block-b2.json`).
- Full `scripts/ci/run_current_product.sh` on the isolated cluster: **826 tests,
  0 failures/errors/skips, 301 executed test files, proof-map gaps empty**;
  baseline integrity and populated multi-database upgrade through0042 passed
  (`.ci/current-product-block-b2/`).

A first runner attempt failed deterministically: the new and replaced definers
omitted the trailing `pg_temp` search path required by
`test_security_definers_are_closed_across_all_runtime_schemas`. The migration was
corrected and both local databases were re-aligned before the final green run; the
failed attempt is retained in `.ci/block-b2-runner.log`.

Not changed: platform-plane continuity and provisioner lifecycle remain pending
(B5); no platform predicate is claimed. The Compose application database remains
at 0037. No commit, push or deployment was performed.

## Platform provisioner lifecycle implementation and validation (2026-09-14, revision 0043)

B1 and B5 were implemented together because the lifecycle surface is the first
consumer of the ratified platform capabilities. Migration0043:

- registers `platform.provisioner.read` (query, PLATFORM, operator) and
  `platform.provisioner.manage_lifecycle` (command, PLATFORM, operator,
  idempotency REQUIRED, revision REQUIRED, AUTHORITY_CHANGE);
- adds both capabilities to the bootstrap trust set and backfills every existing
  active platform controller that already holds an active
  `platform.tenant_provisioner.provision` grant, so creating provisioners still
  grants neither identity recovery nor authority over the creator;
- adds `request_engine.platform_authority_lifecycle_facts`, an append-only private
  audit boundary with no runtime table access; only the control definer writes it
  through the lifecycle command;
- adds `request_platform.principal_is_effective_platform_controller` and
  `request_platform.assert_other_platform_controller`, owned by the control
  definer because platform bindings are invisible under tenant RLS without
  BYPASSRLS;
- adds `request_platform.read_platform_provisioners` for the dedicated read login;
- adds `request_platform.transition_native_platform_provisioner`: one command with
  the platform Principal set as serialization root, actor and target revision
  checks, replay comparison, an action-specific reason set, credential-path
  validation on reactivate and terminal revoke that also revokes standing grants
  without deleting organizations.

HTTP surface (private control app only): `GET /v1/platform/provisioners`,
`GET /v1/platform/provisioners/{principal_id}` and
`POST /v1/platform/provisioners/{principal_id}:suspend|reactivate|revoke`, with
stable operationIds, `Idempotency-Key` required on commands, `expected_revision`
required and `no-store`. The bootstrap root is deliberately not addressable as a
provisioner (404); the authoritative last-controller guard remains the database
backstop.

Executed evidence (PostgreSQL18.6, dedicated test DB):

- 13 DB proofs in `tests/db/test_platform_provisioner_lifecycle.py`: revisioned
  suspend/reactivate/terminal revoke with audit facts, replay idempotency and key
  reuse conflict, stale actor/target revisions, three independent broken native
  paths on reactivate, last-platform-controller protection, non-provisioner
  targets, missing lifecycle authority, app-role denial, append-only facts and a
  two-connection serialization race.
- E2E journey `tests/e2e/test_native_platform_provisioner_lifecycle_http.py`:
  bootstrap, list/get, 401/404/409/422 semantics, suspend/reactivate/revoke over
  HTTP with replay, stale revision, terminal state, capability denial for the
  provisioner, OpenAPI operationIds and authoritative DB facts.
- `python-quality`: **12/12 PASS** (`.ci/python-quality-block-b5.json`).
- Full `scripts/ci/run_current_product.sh` on the isolated cluster: **840 tests,
  0 failures/errors/skips, 303 executed test files, proof-map gaps empty**;
  baseline integrity and populated multi-database upgrade through 0043 passed
  (`.ci/current-product-block-b5/`).

Honest limits and deployment ordering:

- 0043 and the control-plane binary must land together. The previous registry
  cannot materialize the new persisted capabilities (platform actor resolution
  fails closed), and the new startup surface check requires the lifecycle
  function, so the private control plane needs one coordinated migrate+restart
  window. This is fail-closed in either split order, not silently permissive.
- D5 is implemented in revision 0044 (see B3 below); the platform Principal set
  lock remains the lifecycle command's row-lock root inside the SHARE gate.
- The lifecycle surface manages provisioners only; bootstrap/root recovery and
  break-glass remain a separate, accepted deployment path (D4).
- D6 remains open until the real environment is named.

Not changed: no tenant capability, route or tool changed; the Compose application
database remains at 0037; no recovery, linking or global-disable surface exists;
no commit, push or deployment was performed.

## B3 — Identity-topology serialization gate (2026-09-15)

Production change (revision `0044_identity_topology_gate`):

- New transaction-scoped advisory gate
  `request_engine.acquire_identity_topology_share()` / `..._exclusive()` with the
  registered key `(1380274257, 1902476357)`, `SECURITY DEFINER` owned by
  `request_engine_schema_owner`, PUBLIC revoked and EXECUTE granted only to
  `request_platform_control_definer` and `request_bootstrap_definer`. Runtime
  roles cannot take the gate directly.
- Every writer that can alter identity bindings, control grants, staff
  memberships or the reachability they express acquires the gate as the first
  statement of its command, before any row lock: 14 direct-DML command functions
  (staff invitation/lifecycle/authority, agent provisioning/authority/lifecycle,
  integration provisioning/authority/status including their `*_state`
  implementations, tenant-root provisioning, platform provisioner
  provisioning/lifecycle) plus the three public integration wrappers, which lock
  a Principal before delegating to their gated `*_state` implementation.
- `request_platform.establish_root` is the only EXCLUSIVE writer: establishing
  the platform root is a global authority modification.
- Command bodies were mechanically re-emitted from head 0043 with exactly one
  inserted statement and no other change; all other statements, validation
  order, ACLs and owners are unchanged.
- Trigger functions `seed_initial_controller_policy`,
  `seed_root_staff_membership` and `seed_root_staff_read_authority` are
  intentionally not gated: they fire from
  `organization_root_provisioning_facts` rows written inside the gated
  `provision_native_organization_root` transaction and are not callable by
  runtime roles.

Evidence (real PostgreSQL 18.6):

- Deterministic inventory proof: enumerates every function whose body writes one
  of the four topology tables, pins the complete writer set and asserts the gate
  is the first statement with the correct mode; any new unclassified writer
  fails the proof.
- Inversion proof: with another connection holding EXCLUSIVE, all 17 command
  entry points (including `establish_root`) block on the advisory gate while
  holding zero `transactionid`, `tuple` or row-level relation locks.
- Containment: SHARE holders do not block each other; SHARE and EXCLUSIVE block
  each other; the gate is transaction-scoped and released on rollback; the
  platform/tenant read projections and native login complete while EXCLUSIVE is
  held; the runtime role is denied direct gate execution.
- Mutual tenant-controller removal: two controllers suspending each other
  concurrently keep exactly one active effective controller; the loser fails
  with a conflict (`23514`, `40001`, `42501` or a PostgreSQL-resolved `40P01`
  deadlock abort), never a zero-controller tenant.
- `python-quality`: **12/12 PASS** (`.ci/python-quality-block-b3.json`).
- Full `scripts/ci/run_current_product.sh` on PostgreSQL 18.6: all groups passed
  with no failures, **305 executed test files, proof-map gaps empty**, baseline
  integrity and populated multi-database upgrade through 0044 passed
  (`.ci/current-product-block-b3/`).

Honest limits:

- The only EXCLUSIVE writer today is root establishment; global disable and
  global authority operations (C/D) must take EXCLUSIVE and still need
  production contention limits/timeouts before they ship.
- Two mutually targeted staff suspensions can resolve through a PostgreSQL
  deadlock abort (`40P01`) instead of a clean continuity rejection, because the
  target membership row is locked before the ordered active-membership set. The
  invariant holds (exactly one transition commits) and the platform adapters map
  `40P01` to a revision conflict, but the staff lock root is not deadlock-free.
- Credential rotation (`request_cmd.rotate_integration_credential`) and
  delegation creation (`request_engine.create_delegation`) do not acquire the
  gate: they do not create or modify identity bindings, control grants or staff
  memberships. If a future global operation enumerates delegations or
  credentials, they must be classified again.
- Migration backfills and superuser maintenance bypass the gate by construction.

## Requirements matrix and decision gates (2026-09-14)

Status vocabulary: `validado` (executed local evidence), `implementado` (code
written, evidence not run), `pendiente` (no owner decision required yet),
`bloqueado` (needs an explicit owner decision first).

| ID | Block | Owner | Status | Evidence / blocker |
| --- | --- | --- | --- | --- |
| P0 | Inventory and closure contract | repo | validado | Head0051, lane match, DB revisions, route/function inventory verified |
| A | Honest enrollment outcome | platform/security | validado | 0041 + typed outcome +503; unit/DB/E2E + mutant + full lane |
| B1 | Split global vs local identity administration | Tenancy | validado (platform provisioner scope) | 0043 registers read/lifecycle capabilities; global recovery/linking remain in C/D |
| B2 | Authentication-capable continuity predicate | Tenancy | validado (tenant + platform planes) | 0042 tenant proofs; 0043 platform predicate + last-controller guard |
| B3 | Identity topology serialization gate | platform/DB | validado | 0044 gate + complete writer inventory + inversion/containment proofs; production contention limits pending C/D |
| B4 | Transaction/idempotency/audit for identity commands | owners | validado (provisioner + governed recovery + tenant identity commands) | 0043 platform facts; 0045 recovery case audit, idempotency and revision; tenant staff/agent/integration commands now append `audit_records` rows (one per effect, replay-safe, secret-free) via the B4 typed schema; `integration_governance_facts` preserved as provenance |
| B5 | Provisioner list/get/suspend/reactivate/revoke | Tenancy platform | validado | 0043 lifecycle command, read projection, terminal revoke, last-controller guard |
| C | Governed recovery and secure delivery | Tenancy + delivery | validado (local; real Vault+SMTP adapter wired; operational acceptance pending D6) | 0045 case/intent/ticket/append-only audit + fenced worker + private HTTP; C-02 real Vault KV v2 store and SMTP channel wired into the control plane and worker, proven against boundary doubles; 0052 per-attempt issuance generation reservation closes the concurrent-issuance discard hole |
| D | Binding lifecycle, dual-proof linking, global disable | Tenancy | validado (native + OIDC, opt-in) | D1 read projection, D1b binding lifecycle (0046), D3 global native disable (0047 + private HTTP journey), D2 self-service native linking with reauthentication freshness (0048/0049), link hardening (0050) and the OIDC second-proof path (0051) implemented and locally validated; OIDC is opt-in and disabled by default |
| E1 | Existing controller-policy upgrade path | Tenancy | bloqueado | Accepted new grant set + auditable deployment ceremony |
| E2 | Identity-aware onboarding readiness | Onboarding + Tenancy | bloqueado | Depends on B2 facts and D2 recovery configuration |
| E3 | Resource-effective authority inspection | owner-backed | pendiente | Needs approved synchronous connection design |
| F | Adversarial journeys and fixture-free acceptance | repo | pendiente | After A–E; F-01 requires a clean native-only instance |
| G | Operational acceptance and publication | operator | bloqueado | D6 environment, ingress/TLS, RPO/RTO, secret store, operators |

Decision gates ratified by ADR 0013 (2026-09-14); operational detail remains for D6:

| ID | Plan recommendation | Status after ADR 0013 |
| --- | --- | --- |
| D1 | Private control plane; explicit HUMAN security authority; requester and approver distinct; provisioner of tenants is not enough | Accepted: double control with a distinct approver; initial authorities come from an explicit auditable ceremony |
| D2 | Pre-verified channel plus dedicated secret store with staging/TTL; no reset secret in audit, ordinary outbox or admin response | Accepted; the real secret store and delivery adapter are still named in D6 |
| D3 | Self-link only with fresh proof of both identities; no email merge or arbitrary administrative linking | Accepted and implemented: native by 0049 (freshness from 0048, hardening 0050) and OIDC by 0051; OIDC is disabled by default and no provider is configured |
| D4 | Always keep at least one effective controller with an authenticatable path; platform exceptions explicit | Accepted and implemented by 0042 (tenant) and 0043 (platform) continuity predicates |
| D5 | Transactional identity-topology advisory gate before existing locks; SHARE for local changes, EXCLUSIVE for global operations | Accepted and implemented by 0044 (complete writer inventory, inversion and containment proofs); set production containment limits/timeouts before global disable ships |
| D6 | Native-only first, separate private control plane, fail-closed configuration | Partially open: name environment, DNS/TLS/ingress, RPO/RTO/SLO, secret manager, delivery channel, operators and deployment approval |

## Native authority suspension validation continuation (2026-09-14)

The owner authorized tests and code again. Existing suspension tests/fixtures and
0040 on the dedicated local DB were discovered, not assumed to be executed proof.
Current branch remains `cohesion/system-optimization`; `origin/development` was
fetched and is0 commits ahead/326 behind this branch. The integration lane matches.

Production change in this continuation: native, workload and OIDC401 handlers now
consistently emit no-store/no-cache while retaining opaque messages, status/code,
Bearer challenge and authority semantics. Migration0040 and applied history were
not modified. Native enrollment under authority suspension still returns the
existing409 `native_identity_already_exists`: fail-closed but misleading UX. A
typed unavailable-versus-duplicate enrollment outcome remains needed; do not
describe this as polished lifecycle ergonomics or conceal it behind green tests.
This gap was closed by revision0041; see the enrollment-outcome section above.

Evidence improvements: rejected direct calls are committed before independent
state comparison (rollback previously concealed potential effects); unexpected
thread exceptions cannot count as normal rejection; consumption success requires
the exact identity, not merely a non-null object. Race observations check the
actual blocking backend PID. Verifier changes remain detectable via fingerprints
without printing password verifiers in assertion diffs. Added catalog proof for
all seven function signatures, owner, definer/search_path and callable boundaries.

Executed evidence, including completion recovered on2026-09-14:

- First DB/HTTP suspension selection:35 passed in159.81s against PostgreSQL18.6,
  `request_engine_current` at0040 on5432. This initial run predates final oracle
  improvements; final evidence must come from the subsequent canonical run.
- Focused auth/cache unit selection:12 passed. Final `python-quality`:12/12 PASS,
  including180 architecture,362 unit and459 module tests. One dependency
  deprecation warning remains in Starlette TestClient; no dependency was changed.
  Artifacts: `.ci/python-quality-native-authority-final.json` and
  `.ci/logs-native-authority-final/`. An earlier Pyright failure in the new
  fingerprint oracle was repaired by explicitly typing its query rows.
- Initial canonical run on5432 failed at the strict baseline role-membership
  check: existing `re_e2e_app_b6cce0ac9aa8` and `re_e2e_worker_743b853fc2e2`
  memberships. They were not deleted/revoked and baseline enforcement was not
  relaxed. Partial artifacts: `.ci/current-product-native-authority-resume/`.
- Created isolated PostgreSQL18 container `request-engine-auth-validation-20260914`
  on127.0.0.1:55689. Fresh0001→0040, immutable baseline integrity and populated
  multi-database upgrades passed. The complete current-product run finished:
  **816 tests,0 failures/errors/skips,18 JUnit XML reports**, including410 E2E
  cases and139 principal-authority cases. This includes the final strengthened
  suspension oracles and catalog proof, not just the initial35-test selection.
  The proof-execution report was recovered and revalidated after session resume;
  its mapped-proof gaps are empty. The completed run was not rerun merely because
  the terminal session handle expired.
  Output directory: `.ci/current-product-native-authority-isolated/`.
- Separate scratch container `request-engine-auth-mutation-20260914` on53388:
  changing session authority lock SHARE→KEY SHARE made the concurrency proof fail
  specifically because suspension stopped waiting. Exact original function was
  restored and the same test passed (1 passed in2.40s). Artifacts:
  `.ci/native-authority-mutant.xml`, `.ci/native-authority-restored.xml`;
  experiment driver `.ci/native_authority_mutation_probe.py`. This intentionally
  red mutant is falsifiability evidence, not a failed final product test.
- In the same scratch cluster, a separate DB with legitimately created native
  identity, credential, session and pending recovery was advanced0039→0040 after
  suspension. All `request_auth` signatures/owners/ACLs/config/volatility and
  existing auth facts were preserved; committed app-role recovery rejection left
  facts unchanged. Driver: `.ci/native_authority_upgrade_probe.py`. These scratch
  drivers are local ignored artifacts, not additional canonical CI tests. The
  scratch container was stopped without deleting its recoverable databases.
- Additional Linux-host Python3.13.15 run using the existing local-CI image,
  frozen lockfile, temporary Linux venv and read-only repository mount:
  **821 unit/module tests passed,0 failures/errors/skips** in114.52s.
  Artifact: `.ci/native-authority-linux-unit.xml`; container
  `request-engine-auth-linux-20260914` exited0. The same Starlette deprecation
  warning remains. This is not a full Linux PostgreSQL/E2E runner certification.

No production/app-DB migration, commit, push, merge or deployment. App DB on5432
was rechecked and remains0037. The PostgreSQL runner used Windows/Python3.13 with
Linux PostgreSQL; unit/module behavior additionally ran under Linux/Python3.13.15.
Neither dirty-tree result is exact-head GitHub evidence. No claim is made
that all identity-plan acceptance journeys or the whole branch are complete.

### Maintainability review limits

Current deterministic scan `.ci/python-quality-signals.json` is a scan, not a
validated `quality-evidence/v2` packet for this dirty source. Formal disposition
is `INSUFFICIENT_CONTEXT` for exact-source certification until packets exist.
Source review found a real evidence concern (rollback before observation), now
repaired; no metric-only splitting was performed. Migration0040 is an explicit
immutable SQL snapshot; the support file owns five closely related auth worlds;
DB and HTTP suites retain scenario locality. Counterargument: concurrency cleanup
and callback-based oracles deserve scrutiny even when file size is harmless.
No human approval is inferred, and semantic judgment does not prove correctness.

## Native authority suspension implementation (2026-09-13 checkpoint)

Following the owner's continuation request, migration0040 closes the disabled
authority gate for credential reads, enrollment, session creation, rotation,
recovery issuance/consumption and credentialed identity commitment. Positive auth
mutations take an authority SHARE lock before identity/credential/proof locks;
restrictive revocation remains available. Applied history0001–0039 is unchanged.
Suspension is not permanent revocation: reenabling allows only otherwise valid
credentials/proofs/sessions, never restores revoked business authority.

No tests were authored or executed in this implementation turn, per owner request.
No migration was applied, and no database, deployment, commit or push was changed.
The previous780-test result is evidence for0039, **not** this new revision.
Validation ownership, adversarial matrix and commands are in
`../testing/native-authority-suspension-validation-handoff.md`.
Governed issuance/delivery, identity/binding administration and operational
acceptance remain pending; this change is not a production certification.

## Native recovery consumption implementation and validation (2026-09-13)

Added `POST /auth/native/password:recover` over the existing native recovery
transaction, with strict secret-bearing input, uniform invalid-proof errors,
204/no-store success, password-policy handling and explicit retry/reconciliation
semantics. No new session, binding, Principal or business grants are issued.
Existing disabled-identity, expiry, one-use and credential/session invalidation
mechanisms remain authoritative. Migration0039 changes recovery locking to
identity before intent, then revalidates the proof. Function signature,
ownership, privileges and semantic effects are preserved.

### Validation executed by the assigned agent (2026-09-13, local PostgreSQL 18.6)

Environment verified before running: Docker `postgres:18` (PostgreSQL 18.6) on
host 5432, dedicated test database `request_engine_current` advanced from 0038 to
0039, Compose application database `request_engine` left at 0037, historical
stopped containers untouched. Only the dedicated test database was migrated.

Executed locally, in order:

- `alembic upgrade head` applied 0039 to `request_engine_current`; catalog
  inspection confirms preserved signature, owner `request_engine_schema_owner`,
  SECURITY DEFINER, pinned `search_path` and `request_engine_app` EXECUTE, and the
  first `FOR UPDATE` now resolves on `native_identities` before any intent lock.
- `tests/unit/platform/security/test_native_human_auth.py`: **9 passed**.
- authored `tests/e2e/test_native_password_recovery.py` +
  `tests/e2e/test_native_enrollment.py`: **2 passed**
  (`.ci/native-recovery-http.xml`).
- new `tests/db/test_native_recovery_lock_order.py`: **1 passed**. With the
  pre-0039 function body temporarily restored, the same proof fails with
  `asyncpg.exceptions.DeadlockDetectedError` (processes waiting on each other's
  transactions), so the lock-order regression proof is not vacuous. The corrected
  function was restored and re-verified immediately.
- new `tests/e2e/test_native_password_recovery_adversarial.py`: **4 passed**:
  concurrent HTTP consumption of one proof under an identity-lock barrier (one
  204, one closed 401, exactly one credential replacement and one consumed
  intent); expired, malformed, injected-selector and oversized input rejected
  without credential/session/intent mutation; revoked binding, membership and
  grant preserved byte-for-byte with no audit/outbox rows and no raw secrets in
  verifiers or intents; native-only composition mounts `nativePasswordRecover`
  with no issuance route and no tool projection.
- `python-quality`: **12/12 steps passed**
  (`.ci/python-quality-native-recovery-http.json`).
- full `scripts/ci/run_current_product.sh` (now including the new DB proof):
  **780 tests, zero failures/errors/skips**, 18 JUnit artifacts, **297 executed
  test files**, proof-map gaps empty; artifacts
  `.ci/current-product-native-recovery-http/`.

Defects found and fixed during validation: two style defects in validator-authored
tests (Ruff `E501` and Ruff-format drift), corrected before the final runs. No
production-code defect was found in the endpoint or migration.

Discovered pre-existing gap at the0039 validation checkpoint: consuming a recovery proof
does not check the `identity_authorities.status` row. With the authority disabled,
the function still replaces the credential and revokes sessions (verified probe).
This predates this block (0009 checks only identity status; issuance and password
login behave the same), but the handoff required rejection. Session
authentication already rejects a disabled authority and runtime readiness reports
503. Extending the credential gate to authority status is a semantic change
(consume + issuance + login for coherence) and was **not** applied in that
validation. The subsequent0040 implementation above addresses it; its proof is pending.

Not done by this validation: commit/push/merge, migration of the Compose
application database, deployment, exact-source `quality-evidence/v2` packets for
the dirty tree. Dirty-tree local green is not GitHub exact-head CI. This is only
consumption, not governed issuance, account linking, disable administration or
complete recovery. Internal token issuance remains unexposed until a separately
authorized anti-takeover workflow exists.

## Published checkpoint verified after user commits (2026-09-12)

### Implementation-only continuation (2026-09-13, new 0038 not applied)

The user asked this session to prioritize implementation and leave test execution
to another agent. The new `GET /v1/me/authority` owner query, typed transport,
app-role snapshot reader, `authority.read_self` capability and immutable initial
controller v3 migration are now authored, along with regression tests and current
route/CI inventory updates. **This block has not run tests, lint/type validation
or its migration.** Import ordering/formatting is not a validation substitute.
Local databases remain at 0037 until a validating agent applies 0038 safely.

The endpoint reports the caller's current active Party relationships, exact scopes,
validity and revisions under an explicit current standing permission. It neither
inspects arbitrary Principals nor certifies resource/booking authorization. The
new policy is v2 plus one delegable operational read; existing roots are untouched.
The private binary now selects v3, so it intentionally cannot start against the
old policy catalog. Do not deploy this unvalidated combination.

Detailed execution/acceptance instructions, exact commands and remaining evidence
gaps are in `../testing/auth-ergonomics-validation-handoff.md`. This supplies the
next validation task; no second agent/task was created or contacted here.

### Validation executed by the assigned agent (2026-09-13, local PostgreSQL 18.6)

The handoff instructions were executed against the dedicated test database
`request_engine_current` after verifying Docker `postgres:18` (PostgreSQL 18.6),
the Compose credentials and the 0037 Alembic revision. `alembic upgrade head`
applied 0038 to that dedicated test database only. The Compose application
database `request_engine` was left at 0037; stopped historical containers were not
restarted or deleted.

Executed locally, in order:

- narrow transport/policy proofs: **33 passed**;
- `tests/db/test_self_authority_reader.py` +
  `tests/db/test_initial_controller_policy.py`: **11 passed** at the authored
  revision; the reader file later reached **6 passed** standalone after the added
  adversarial cases below;
- PostgreSQL HTTP proofs (`test_native_platform_provisioner_http`,
  `test_native_agent_lifecycle`, `test_platform_control_runtime_factory`,
  `test_http_tenant_isolation_matrix`): **72 passed**;
- `python-quality`: **12/12 steps passed** (architecture 180, unit 359, modules
  459; Ruff lint/format, Pyright, secret scan, SAST, dependency audit);
- full `scripts/ci/run_current_product.sh`: **774 tests, zero failures/errors/
  skips, 294 executed test files, proof-map gaps empty**, including 403 E2E and the
  populated multi-database upgrade proof. Artifacts:
  `.ci/current-product-self-authority/` (18 JUnit XML files plus
  `proof-execution.json`); logs: `.ci/logs-self-authority/`.

Defects found and fixed during validation:

1. Ruff `E501` in the authored `tests/db/test_self_authority_reader.py` blocked the
   canonical lint step (the implementation block had never run lint). Two overlong
   lines were wrapped; no behavior changed.
2. The first native-agent self-inspection journey returned
   `agent_governance_forbidden` because the helper-built E2E root controller lacked
   a delegable operational `authority.read_self` ceiling. The test world now grants
   that precondition through its existing helper. Production code was not changed.
3. Adversarial proofs required by the handoff were added: same-tenant
   second-Principal isolation across HUMAN/INTEGRATION/AGENT kinds; an active
   delegation alone does not satisfy the standing-grant requirement; a durable
   mutation-freedom fingerprint (grants, representations, Principal revision,
   audit/outbox); a native AGENT HTTP self-inspection journey with policy and grant
   removal; and a populated v2 root created at 0037 and verified across
   upgrade/replay by the v3 binary in
   `scripts/db/prove_multidatabase_migration_compatibility.py`.

Not done by this validation: Linux/Python 3.13 repetition; exact-source
`quality-evidence/v2` packets for the dirty tree; 0038 was not applied to the
Compose application database; no commit, push, PR or deployment. The
maintainability scan reports one `QR-FSIZE-001` review candidate
(`tests/db/test_self_authority_reader.py`, 269 effective LOC) measured against the
committed `head_sha`; semantic disposition recorded here as **HEALTHY_AS_IS**
(one cohesive reader-contract proof set; no independently changing responsibility).
Exact-head GitHub CI remains the merge authority.

### Subsequent local agent-discovery work (not covered by that CI run)

The working tree now admits authenticated AGENT callers to the explicit read-only
operation catalog after a fresh policy read. Canonical capability registration,
current granted/allowed/denied authority and the shared execution risk predicate
filter discovery; other unmarked routes and missing policies still deny agents.
The response links canonical OpenAPI schemas, reports Party/override requirements,
policy revision and mandatory owner validation, and is not cacheable. This is HTTP
self-discovery, not MCP or object-specific authorization inspection.

Focused evidence: 27 unit tests passed; the native agent PostgreSQL HTTP lifecycle
passed on PostgreSQL 18.6 (`.ci/agent-catalog-e2e-20260912.xml`), including policy
changes reflected in discovery, excluded booking still denied on execution,
canonical schema-pointer resolution and unchanged mutation budget. Final
`python-quality` passed all 12 steps
(`.ci/python-quality-agent-catalog-final-20260912.json`). The first quality attempt
found two typing errors, corrected before the final run; a newly authored test
initially used an incorrect override-capability name, also corrected against the
existing canonical contract. No production permission was renamed for that test.

The full PostgreSQL current-product lane completed in
`.ci/current-product-agent-catalog-20260912/`: **763 tests, zero failures/errors/
skips, 293 executed files and no proof-map gaps**. It had already completed when
interruption was attempted after the user's change of instruction. This result
covers the catalog block, NOT the later0038/self-authority changes. No migration, OIDC enablement, business
endpoint semantics, provider integration or deployment configuration changed in
this discovery block.

Local signal inspection against `origin/development` found affected candidates
`QR-c3835e3f71be` (catalog, 148 effective LOC), `QR-6516b1562f44` (projection McCabe
12), `QR-91863edf578f` (native agent journey, 359 LOC), `QR-b1f26caf2730` (policy
tests, 288 LOC) and `QR-7478919bd1db` (catalog tests, 146 LOC), in
`.ci/agent-catalog-working-tree-signals.json`. Formal disposition for these dirty
sources: **INSUFFICIENT_CONTEXT**, high confidence that exact-source validated
packets are not yet available, not a defect verdict. The default HEAD-parent scan
does not select all tracked uncommitted changes; its empty candidate list is not
evidence that these files are below review thresholds. The broader scan measures
working files but its head SHA still names the committed checkpoint.

Protected properties are cohesion, reasoning locality and fail-closed policy.
Source inspection shows one pure OpenAPI projection with sequential rejection
filters, one request policy boundary and focused policy/journey proofs. A
counterargument is that nested schema validation plus policy filtering adds
reasoning cost. Do not introduce forwarding modules or duplicate risk policy to
lower metrics. Required follow-up is a matching validated packet and semantic
disposition at publication; executed architecture/type/behavior results are
recorded separately above. No human review or author approval is inferred.

The user committed and published the accumulated work at
`ca30131c10ba3c5e8058b49c4595751ebcc4eed4` on `cohesion/system-optimization`.
[PR #132](https://github.com/JulioMarte/request-engine/pull/132) targets
`development` and remains open. [CI run 34723690888](https://github.com/JulioMarte/request-engine/actions/runs/34723690888)
completed successfully: Python quality/architecture, observability, PostgreSQL 18
design history, current-product proof and the aggregate prerequisite status.
The actual execution steps ran; this is not a skipped-lane aggregate.

Downloaded current-product artifacts contain **763 passed tests, including 400
E2E**, zero failures/errors/skips, **293 executed test files**, and `gaps: []`.
Quality evidence identifies `test_mode: PR_INTEGRATION_CANDIDATE`, source head
`ca30131c10ba3c5e8058b49c4595751ebcc4eed4` and tested merge candidate
`273a94e2232979fb011358d321b9a0128f5272d1`. Both commits have the identical tree
`8a7d511855f6e03f7067e8e9fdab46e5c1f19093`. This supersedes missing exact-source
CI evidence for that published checkpoint, not the remaining product acceptance
gaps or any later source changes.

Artifacts were downloaded to `.ci/github-34723690888/`. Validated
`quality-evidence/v2` packets now exist there, including the affected private
factory/upgrade/policy/HTTP-journey candidates. The earlier missing-packet
disposition below describes the pre-publication checkpoint; packet availability
does not itself supply semantic approval or a human review verdict.

The local canonical run `.ci/current-product-agent-inspection-20260912/` did
**not** finish green: the proof PostgreSQL received a fast-shutdown request at
19:45:24 UTC, terminating an active E2E connection, and exited 137. Docker reports
`OOMKilled: false`; the shutdown initiator is not established. The E2E phase
recorded 210 passed, one failed and 191 errors (connection/fixture cascade), and
the runner stopped before final proof-map validation. It must not be described
as a successful local full run. An earlier separate Linux repetition failed
during collection with `Cannot allocate memory`; that also supplies no behavior
proof.

The local Docker environment changed during the pause: `request-engine-postgres-1`
now serves PostgreSQL **18.6** on 5432, while the older proof/habitual containers
remain stopped and were not deleted or restarted. `request_engine_current` was
already at 0037 and is the dedicated test database. Compose's configured
`request_engine` database had no application tables; applying the unchanged
Alembic chain there completed successfully through `0037_agent_inspection_policy`.
No identities, tenant roots or production credentials were invented by migration.
This closes the local schema mismatch, not runtime enrollment/deployment setup.

No additional push, PR mutation, merge, container deletion or production
deployment was performed by this verification. The final local Linux repetition
used `request_engine_current`, not Compose's application database, and passed
**19 tests** under Python 3.13.15 against PostgreSQL 18.6:
`.ci/linux-agent-inspection-final-20260912.xml`. It covers policy immutability and
concurrency, current-authority/tenant-scoped inspection, the native-controller
agent booking journey and private-runtime readiness/privilege drift. The earlier
failed local artifacts are retained, not relabeled as successes.

## Verified implementation

| Area | Implemented boundary and evidence |
| --- | --- |
| Native-first HTTP | Explicit ASGI factory, required secret configuration, native enrollment/session endpoints, optional OIDC disabled by default. Real TCP startup/OpenAPI/auth rejection proof in `tests/e2e/test_http_runtime_factory.py`. |
| Runtime database identity | Startup rejects privileged logins and membership in any role other than the app role. Real PostgreSQL tests include non-inherited worker, private-definer and read-all-data memberships. |
| Runtime native authority | Startup rejects absent, disabled and wrong-kind native-authority configuration. A bounded, boolean-only DB projection backs readiness; disabling the authority while serving TCP produces 503 with no details and no-store. It does not certify the full schema head or worker health. |
| Native credential inputs | Login/rotation reject blank handles and injected fields. Invalid new passwords produce typed 422 after validating the current credential, including byte-size/UTF-8 failures, without replacing credentials or revoking sessions. Successful HTTP rotation invalidates old passwords/sessions without provisioning a Principal. |
| Native staff | Invite, activate, bounded authority replacement and suspension execute through HTTP. List/detail expose revisions and standing grants under explicit `staff.read`, with bounded UUID pagination and foreign/random-ID opacity. The DB reader rechecks a revoked grant even when passed a previously valid actor. Operational grants remain non-delegable and do not manufacture Party Representations. |
| Integration workloads | HUMAN-controlled provisioning, bounded operational authority, list/detail with revisions, activation/suspension/revocation and credential rotation. HTTP booking journey proves immediate old-token rejection and secret-free idempotent rotation replay. |
| Integration provenance | Appended governance facts, immutable origin and credential metadata without reusable secrets. Existing legacy state is identified rather than attributed to an invented creator. |
| Optional OIDC bearer | Strict configured access-token profile, bounded JWKS fetching/cache, current-authority revalidation and explicit subject-to-Principal binding. Native/external coexistence and external-authority removal are tested with a controlled external boundary. |
| Tenant references | Appended composite foreign keys and scoped provenance guards distinguish tenant-local references from legitimate platform provenance. Applied baseline history is unchanged. |
| Operation metadata | Ten manually registered configuration/discovery operations now have explicit stable operation IDs and capability/owner metadata. This does not automatically expose them as agent tools. |
| Resource configuration | Creating a Resource without weekly windows no longer fabricates an assignment; this matches the accepted onboarding semantics. |

Important distinction: INTEGRATION workload access for a website's server is not
the B2B external-human identity-provider adapter slice. A workload credential must
not be embedded in browser JavaScript.

## Agent inspection continuation (2026-09-12, revision 0037)

`GET /v1/agents` and `GET /v1/agents/{agent_principal_id}` now expose current
profile/authority revisions, lifecycle and sorted standing capabilities under
explicit HUMAN `agent.read`. The adapter rechecks current grant/Principal state
and reads target data in one PostgreSQL statement snapshot; foreign and random
IDs are opaque. No credentials or effective Party/resource permission claims are
returned. See `agent-governance-inspection.md` for the owner operation contract.

Additive 0037 appends immutable `tenant-controller-v2` (v1 plus `agent.read`),
used only for new native roots. Both the habitual PostgreSQL 18.6 database on
5432 and the isolated proof cluster have been migrated. Startup/readiness
validate the selected policy through the private selector without gaining table
access. Existing v1/no-policy roots and their revocations are not upgraded.

Executed evidence so far:

- Focused DB/HTTP run: 17 passed and one failed because its final policy-key
  assertion still expected v1. Updated the assertion to the explicit v2 default;
  the earlier failure is retained in `.ci/agent-inspection-focused-20260912.xml`.
- Final HTTP/OpenAPI/readiness repetition: **15 passed** in
  `.ci/agent-inspection-http-final-20260912.xml`, including absent-selected-policy
  readiness failure and the controller/agent booking journey.
- Python-quality: all 12 steps passed in
  `.ci/python-quality-agent-inspection-final-20260912.json`.
- Populated physical upgrades passed through the multidatabase proof: create a
  real root at 0035 and another with policy v1 at 0036, revoke authority, upgrade
  to 0037, select v2 and replay; original facts, grants and revocations persist.

The initial migration attempt rolled back before applying because SQLAlchemy
parsed a compact JSON `:true` as a bind parameter. The corrected literal applied
successfully; subsequent JSON whitespace formatting did not change stored data.
The canonical local attempt subsequently failed during container shutdown; the
final Linux repetition passed. Exact-source GitHub evidence subsequently became
available after the user's commits, as recorded above. Earlier 759-test evidence
is not assigned to these new changes. No deployment was performed.

## Agent handoff and populated upgrade continuation (2026-09-12, still 0036)

The native controller now completes the AGENT journey without SQL manager grants
or SQL revision lookups: provision, bounded standing authority, risk/tool policy,
activation, and booking for a patient. Agent creation returns the actual initial
Principal `authority_revision` separately from `profile_revision`, persists that
snapshot with the idempotent result and marks the response `no-store`. Replay
never returns the workload secret or invents current revisions. Historical cached
responses lacking the added field return null. A dedicated current-state agent
inspection/refresh API is still missing; the creation response does not replace it.
No schema migration, database privilege or new capability was needed for this fix.

The focused final HTTP/agent-unit selection passed **6** tests:
`.ci/initial-controller-agent-final-20260912.xml`. It includes a legacy-cache-shape
compatibility input after real provisioning, without rewriting authority facts.
The populated physical upgrade proof also passed on PostgreSQL 18.6 through
`scripts/db/prove_multidatabase_migration_compatibility.py`: install 0035, create a
real root through its private command, revoke `staff.read`, upgrade to HEAD, then
select the newer policy and replay. Grant IDs, statuses, revisions and provenance
remain unchanged, and the root policy remains absent. Its isolated temporary
database is deleted afterwards, never the source database.

The previous completed 0036 canonical run passed **759** tests (**399 E2E**), zero
failures/errors/skips and no mapped-proof gaps:
`.ci/current-product-initial-controller-20260911/`. The Linux repetition passed
**17** tests under Python 3.13.15: `.ci/linux-initial-controller-20260912.xml`.
Those results precede the agent response addition above. Final Python-quality
passed every step in `.ci/python-quality-initial-controller-agent-final-20260912.json`;
the first attempt stopped on one overlong test SQL string, corrected without
changing its assertion. The final canonical run subsequently completed with
**759** tests (**399 E2E**), zero failures/errors/skips and no mapped-proof gaps:
`.ci/current-product-initial-controller-agent-20260912/`. These results include
the agent response addition, but precede the separate 0037 inspection changes.
The final Linux repetition of the affected native-platform/agent-lifecycle
journeys passed **2** tests under Python 3.13.15:
`.ci/linux-initial-controller-agent-final-20260912.xml`. This run includes the
new authority-revision response and legacy-cache compatibility proof.

## Initial controller policy continuation (2026-09-11, revision 0036)

Native organization creation now explicitly selects immutable `tenant-controller-v1`.
Revision 0036 records it on the root and materializes 25 additional grants atomically;
the resulting controller has 33 active capabilities, with no wildcard, platform
authority or automatic inheritance of future registry additions. Existing roots
retain their original policy, and replay never restores revoked grants. The
private process requires the policy selector at startup. See
`initial-controller-policy.md` for exact authority and rollout semantics.

Executed focused PostgreSQL 18 evidence:

- 16 runtime/HTTP/policy/legacy-root cases passed in
  `.ci/initial-controller-policy-runtime-20260911.xml`. The CLI/bootstrap-to-HTTP
  controller configures actual bookable supply, books a patient and provisions,
  bounds and activates an integration without inserting controller grants.
  The workload can look up the patient but cannot read staff. Workload-authority
  installation configuration is still explicitly seeded; this is not a fully
  fixture-free installation journey.
- 7 final policy/concurrency/legacy-replay cases passed in
  `.ci/initial-controller-race-final-20260911.xml`: independent connections
  demonstrably wait on the creator lock, then produce one root and 33 active
  grants; a selected-policy replay leaves an old root's original grants unchanged.
  The first attempt exposed two test errors: counting historical revoked grants
  as active duplicates, and reading setup data under the intentionally restricted
  control role. Corrected oracles preserve the seven historical revoked records.
- The full DB selection passed 316 cases in `.ci/db-initial-controller-20260911.xml`
  before the extra concurrency case and strengthened legacy-replay assertion.
  Those changes passed the seven-case final selection above.
- Python-quality passed every step in
  `.ci/python-quality-initial-controller-final-20260911.json`; the last two test-only
  corrections are additionally checked by targeted Ruff/Pyright and PostgreSQL.

Both local PostgreSQL clusters are now at 0036. The auxiliary cluster first
rejected connections during crash recovery from its earlier interrupted shutdown;
no migration/test executed during those two rejected connection attempts. Recovery
completed normally before the upgrade and focused proof. The completed 0036
canonical result is recorded above; the older 0035 result below does not certify
0036. The later auxiliary shutdown completed its checkpoint and exited cleanly.
No deployment or publication is claimed.

## Private process continuation (2026-09-11, historical checkpoint 0035)

`bootstrap.platform_server:create_app` now owns the three distinct pool lifecycles,
validates explicit deployment configuration and verifies real login privileges
at startup and readiness. It rejects unexpected memberships (including NOINHERIT),
direct read/write relation privileges, extra callable private functions, app-to-platform
privilege crossover and inactive native authority. Endpoint/user mismatches and
hidden URL routing overrides fail before startup. External identity remains optional.
The deployment contract and remaining ingress/TLS obligations are described in
`http-runtime-deployment.md`.

The canonical PostgreSQL 18.6 runner completed **754** tests, including **399 E2E**,
with zero failures/errors/skips and no mapped-proof execution gaps:
`.ci/current-product-private-platform-20260911/`. Baseline integrity and the
controlled second-database migration checks passed. The explicit host/database
validation was added during the earlier SQL phases, before E2E loaded the factory;
the final Python-quality run passed all steps separately:
`.ci/python-quality-private-platform-explicit-20260911.json`. This includes the
ten pure configuration proofs; nine real-PostgreSQL private-process cases include
real TCP and privilege/authority drift. The complete DB selection also passed
**312** tests on schema 0035: `.ci/local-db-platform-root-20260911.xml`.

The first Linux repetition failed during collection with local memory exhaustion,
before executing any test; it is not behavioral evidence. The auxiliary proof
container was stopped (not deleted) after the global runner completed to free
memory for a sequential Linux retry. The habitual PostgreSQL container on port
5432 remains running and both databases retain revision 0035. The sequential Linux
retry passed **31** tests under Python 3.13.15:
`.ci/linux-private-platform-sequential-20260911.xml`. No exact-SHA publication
certificate or production deployment is claimed.

The adversarial fixture initially left two newly created control-test roles with
their deliberately injected grants after teardown failed. Both were verified to
own zero objects and removed with their test grants; no product rows or pre-existing
roles were removed. Fixture cleanup now removes its own temporary privileges
before dropping its own role. No migration was edited for this process work.

## Native platform provisioning continuation (2026-09-11, revision 0035)

The separate private control API now supports native provisioner creation and
organization/first-controller creation. No external provider is required. The
ordinary native tenant API does not install these routes. Revision 0035 adds
atomic native provisioner binding; organization creation reuses the existing
root function with full-intent idempotency provenance rather than editing history.
The operation/connection design is in `http-runtime-deployment.md`.

Focused real PostgreSQL 18 proof passed **6** cases:
`.ci/native-platform-root-http-final-20260911.xml`. This includes independent
competing transactions, atomic rollback, payload conflicts, replay after target
revocation, creator authority revocation, and the bootstrap-to-controller HTTP
journey without manually inserted bindings or tenant provisioning facts. The
tenant controller can inspect staff; the platform provisioner cannot enter that
tenant, and the tenant controller cannot provision platform organizations.

Validation history is not hidden: the first 0035 quality run stopped on 17 type
errors; after correction a second reached architecture and identified the missing
private composition entry. The module-owned transport/import restriction was
preserved while registering this explicit composition. The first expanded HTTP
test expected 401 for an authenticated identity without plane authority; the
existing resolver correctly returned 403, and the assertion was corrected.
The full Python-quality job passed every step:
`.ci/python-quality-platform-root-20260911.json`. The canonical PostgreSQL 18.6
runner passed **745** tests, including **390 E2E**, with zero failures/errors/skips
and no mapped-proof execution gaps:
`.ci/current-product-platform-root-final-20260911/`. Baseline integrity and the
controlled second-database upgrade also passed. Its first attempt found a missing
exact-owner catalog entry for the new private function; that entry was pinned to
its full signature, without adding a generally trusted definer owner.
Linux/Python 3.13.15 passed **22** platform/authentication/TCP cases independently:
`.ci/linux-platform-root-20260911.xml`. These results certify only this local
checkpoint, not GitHub exact-head CI or production deployment.

This closes the basic native A-to-B-to-tenant transport journey, not the entire
production objective. Initial operational controller policy, recovery/binding
administration and the remaining plan acceptance journeys are still incomplete.

## Platform continuation (2026-09-11, revision 0034)

An actual least-privilege native Platform Controller resolution exposed the
pre-existing platform-binding read defect: FORCE RLS hid the bootstrap-created
binding from the function's schema-owner execution context. Forward migration
`0034_platform_binding_read` assigns that exact read to the existing private
platform-read definer with eight explicitly reviewed binding SELECT columns.
No applied revision was edited, and the app role remains unable to read platform
authority directly. See `http-runtime-deployment.md` for the connection design.

The native runtime now offers an opt-in provider-neutral platform HTTP actor
resolver requiring a separate platform-read session factory. It rejects tenant
selectors, ignores forged authority headers and re-reads current RE binding/grants.
Ordinary native startup does not enable it and OIDC remains optional.

The real bootstrap/login/actor proof, private definer catalog and platform/app
separation tests passed **10** cases on PostgreSQL 18.6 after the fix:
`.ci/platform-http-definer-final-20260911.xml`. The first attempt correctly failed
on the hidden binding. A subsequent composition attempt incorrectly used the app
pool for platform authority and failed on its intentional privilege boundary;
the fix uses a distinct minimally privileged read login, not widened app grants.

Python-quality passed all steps after the implementation:
`.ci/python-quality-platform-http-final-20260911.json`. The first quality attempt
stopped on one formatting discrepancy; formatting was corrected and the entire
job rerun. The full current-product runner passed **743** tests, including **389
E2E**, with zero failures/errors/skips and no mapped-proof execution gaps:
`.ci/current-product-platform-http-20260911/`. Baseline integrity and the second
database's upgrade to 0034 passed as part of that runner. Linux/Python 3.13.15
also passed **17** platform-boundary and TCP runtime cases independently:
`.ci/linux-platform-http-20260911.xml`.
The complete local PostgreSQL selection passed **311** tests on revision 0034:
`.ci/local-db-platform-http-20260911.xml`. The canonical runner has also completed
its **87** principal-authority tests and baseline/multidatabase migration checks.
Prior 0033 evidence below does not certify revision 0034.
At the 0034 checkpoint, platform provisioning endpoints and the native provisioner
binding command were not implemented; the 0035 continuation above supersedes that
status. Complete initial controller policy remains unfinished.

## Continuation through revision 0033

The habitual PostgreSQL 18.6 instance on port 5432 now has
`0033_staff_terminal_revocation`. Appended revisions 0031-0033 add explicit staff
inspection, the private native-authority readiness projection and complete terminal
staff revocation; revisions 0001-0030 were not rewritten by this continuation.

The expanded HTTP staff journey exposed a real command/schema mismatch: the
accepted state machine permitted revoking invited/suspended memberships, while
the command accepted only active members. Revision 0033 fixes the command and also
rejects missing/nonpositive expected revisions and missing provenance at the DB
boundary. It retains self-transition rejection, tenant scoping, current-manager
checks, last-controller protection and atomic session invalidation.

The native password-rotation HTTP route also lacked a typed mapping for password
policy failures. The failing PostgreSQL-backed regression was reproduced before
the transport correction. Credential policy lengths, hashing parameters and
authority assignment were not relaxed.

Clean, completed continuation evidence:

- The complete canonical current-product runner finished on PostgreSQL 18.6 at
  revision 0033: **740 passed**, including **389 E2E**; JUnit records zero failures,
  errors or skips (two non-PostgreSQL E2E cases were deselected). Accepted baseline
  integrity, multidatabase upgrade and mapped-proof execution checks also passed.
  Artifacts: `.ci/current-product-auth-final-20260910/`. This run had already
  executed its authority block before the two new concurrency cases below were
  added; their subsequent 86-case authority rerun is separate evidence, not an
  invented 742-case full-run result. Production source did not change between them.
- The later adversarial closure adds both serialized orders of competing staff
  reactivation/revocation. Actual PostgreSQL lock-wait observation precedes commit;
  the stale loser returns `40001` without overwriting state or session epoch.
  The complete current-product principal-authority selection was rerun afterward:
  **86 passed**, `.ci/principal-authority-staff-race-20260910.xml`. Its focused
  lifecycle suite passed **12** cases, `.ci/staff-lifecycle-concurrency-20260910.xml`.
  The same **12** lifecycle cases also passed independently on Linux/Python
  3.13.15 against PostgreSQL 18.6: `.ci/linux-staff-race-20260910.xml`.
- Python-quality was rerun after those concurrency proofs and passed every step:
  `.ci/python-quality-staff-race-20260910.json` and `.ci/logs-staff-race-20260910/`.
  No production code, grants or applied migration changed in this proof-only step.
- The final Python-quality job passed all steps; machine-readable results are in
  `.ci/python-quality-auth-final-20260910.json` with its referenced logs.
- Linux/Python 3.13.15 independently passed **28** focused PostgreSQL, real TCP,
  native enrollment/rotation, staff/integration/OIDC, provisioning and hard-process
  crash proofs on revision 0033: `.ci/linux-auth-final-20260910.xml`.
- The complete host `tests/db -m postgres` selection passed on revision 0033:
  **308 passed**, `.ci/local-auth-db-final-20260910.xml`.
- A separate disposable PostgreSQL 18.6 cluster was installed at 0030, populated
  with original controllers and upgraded through 0033. Three one-off local
  scenarios passed: missing staff.read was added once; an existing active grant
  was not duplicated; a revoked grant stayed revoked. Every previously existing
  grant retained its ID, key, state, delegability and revision. This is local
  upgrade evidence, not a newly installed canonical CI test. The proof container
  `request-engine-auth-upgrade-20260910` was stopped, not deleted.
- The earlier complete canonical run on revision 0032 passed **735** tests,
  including **389** E2E, with clean baseline/multidatabase/proof-map checks. This
  earlier result does not certify the subsequent 0033 migration.

The first staff-read canonical attempt failed because two new routes lacked
entries in the general isolation probe matrix. Those probes were added with the
existing DB-authority rejection semantics; the real authenticated staff journey
separately proves foreign/random membership opacity. An attempted test run also
overlapped a focused host test with Linux tests on the same database. That run was
invalidated/interrupted and is not release evidence. The 28-test Linux result
above was executed again without that overlap. The two canonical test clusters
are separate from each other; tests must remain serialized within each database.

## Earlier executed evidence (revision 0030)

The source was the dirty local `cohesion/system-optimization` worktree based on
`43f889da023ef4559ddea0a902b720a5c3920df3`, not a new committed/published release.
These results do not certify that commit alone or replace exact-head GitHub CI.

- The local database on port 5432 was verified as PostgreSQL 18.6 at revision
  `0030_integration_provenance` for this checkpoint.
- `scripts/ci/ci_jobs.py python-quality` passed after the runtime/staff/crash-proof
  changes: lint, format, strict typing, security/dependency scans, architecture,
  unit and module checks. The final repeat including the staff-capability
  description correction also passed; its machine-readable result is recorded below.
- `scripts/ci/run_current_product.sh` completed on a separately created PostgreSQL
  18.6 cluster through Git Bash and Windows Python: **725 tests passed**, including
  **384 E2E tests**, with 2 E2E cases deselected by the PostgreSQL marker. Accepted
  baseline integrity, second-database migration and proof-map execution also passed.
- The complete `tests/db` PostgreSQL selection passed independently on the local
  port-5432 database: **298 passed**.
- A Linux container using Python 3.13.15 reran the critical HTTP runtime, native
  staff/provisioning, integration booking/rotation, OIDC and process-crash proofs:
  **10 passed** against real PostgreSQL 18.6. This includes the real POSIX SIGKILL
  branch, not just the Windows hard-termination adaptation.

Local generated evidence (ignored by Git):

```text
.ci/current-product-local-20260910/*.xml
.ci/current-product-local-20260910/baseline-integrity.json
.ci/current-product-local-20260910/proof-execution.json
.ci/local-auth-db-20260910.xml
.ci/linux-auth-20260910.xml
.ci/python-quality-auth-20260910.json
```

The Windows crash test originally failed before testing recovery because SIGKILL
is unavailable on Windows. The test now uses unconditional TerminateProcess there,
retains SIGKILL on POSIX, checks the exact expected termination code and bounds
subprocess execution. Lease recovery and stale-worker fencing assertions remain.

An attempted fresh database installation in the habitual cluster failed closed
because two existing `re_e2e_*` logins retain app/worker memberships. The immutable
baseline requires its audited role topology. The clean-cluster proof did not
remove those logins or weaken that guard. Installing another database into an
already provisioned runtime cluster remains an operational limitation to resolve
explicitly; clean-cluster installation and the runner's controlled multibase case
are not evidence that every existing role topology is supported.

The empty database from that failed first attempt was verified to contain no
user tables and removed. The separate proof container was stopped, not deleted;
its database remains recoverable by restarting `request-engine-proof-20260910`.
The habitual port-5432 container remains running.

## Still required by the identity plan

1. Operational acceptance of the private platform-control service in the selected
   deployment environment. The authenticated HTTP journey and separately configured
   process now exist; credentials, private ingress and TLS are not yet deployed.
2. Explicit management of older controller policies. Current-state agent inspection
   is implemented in 0037; its new full evidence is tracked above. The initial policy
   now has HTTP human/integration/agent
   booking proof and populated physical-upgrade evidence; legacy roots deliberately
   retain their authority rather than being silently upgraded on replay.
3. Party/resource-effective authority inspection. Native staff invitation cancellation,
   activation, suspension, reactivation with fresh login and terminal revocation now
   have owner-backed HTTP proof. Staff list/detail and client-visible revisions are
   implemented; active standing grants intentionally do not claim effective access
   to every Party/resource.
4. Real secret-store/delivery adapter and operational acceptance for the governed
   recovery/disable, provisioner lifecycle and authority/binding administration
   surfaces. Those surfaces (provisioner lifecycle 0043, governed recovery 0045,
   binding lifecycle 0046, global native disable 0047) are implemented and locally
   validated; the production delivery adapter and D6 operational acceptance remain.
5. A real external-human B2B identity adapter and conformance/portability evidence,
   including signed events, replay/out-of-order handling and reconciliation where
   that provider facet is supported. Generic OIDC verification now also backs
   self-service linking (0051), but it does not supply that B2B adapter.
6. Onboarding identity/controller/staff prerequisites and actionable machine-readable
   blockers. Business supply readiness currently does not prove identity readiness.
7. The complete fixture-free acceptance journeys and their adversarial closure,
   including production deployment, credentials/TLS/ingress limits, worker/provider
   delivery, backup/recovery and operational acceptance in the intended environment.

The next implementation priorities are the C-02 real delivery adapter (D6), the B4
append-only audit for tenant staff/agent/integration commands, the E blocks (E1
controller-policy upgrade, E2 identity-aware onboarding readiness, E3
resource-effective authority inspection), the F adversarial journeys and G/D6
operational acceptance. The providerless creation and initial authority journeys
now exist; their production operational acceptance remains separate. External
identity must remain optional throughout that work.

## Review and publication limits

No commit, push, PR, merge or production deployment was performed for this
checkpoint. Existing unrelated work was preserved. The single integration lane
still names the current branch; `origin/development` was fetched and the branch
was verified as 0 commits behind and 315 ahead.

Maintainability scans are not semantic approval. Exact-source validated review
packets and per-candidate dispositions are still required before calling the
review/publish cycle complete. A dirty-tree test result is not an exact-SHA
publication certificate; the managed pre-push gate and GitHub CI still apply.

The 2026-09-12 scan also reports `QR-9d3bb247f80f` (upgrade evidence, 128
effective LOC) and `QR-05d049acb91d` (native platform HTTP journey, 440 effective
LOC), both `QR-FSIZE-001`. Formal packet-review disposition:
`INSUFFICIENT_CONTEXT` (high confidence that validated exact-source packets are
absent, not a verdict that the code is defective). Protected properties are
cohesion and reasoning locality. Source inspection finds one migration scenario
and one end-to-end authority journey respectively; a counterargument is that the
long journey can make failure localization harder. Do not split them merely to
cross the LOC threshold. Generate/validate exact-source packets and obtain the
required review before claiming the review cycle complete; author inspection and
green tests are not independent approval. The measurements above come from
`.ci/python-quality-signals.json`, which remains a scan, not an evidence packet.

The 0037 scan updates those two candidates to 137 and 470 effective LOC,
respectively, and reports `QR-ff49fe31057b` (private factory, 160) and
`QR-9e8841575714` (policy proof, 212). The same `INSUFFICIENT_CONTEXT` formal
packet disposition applies: no validated exact-source packets are present.
Source inspection concerns are failure localization in the growing HTTP journey
and keeping owner policy selection separate from technical readiness checks.
The factory consumes explicit owner composition metadata; the reader remains
one tenant-scoped query responsibility with a typed application port and HTTP
DTO mapping. No extraction or authority-rule waiver was made to reduce metrics.
Architecture, lint/types and behavior proofs remain required independently;
`human_verdict` is null because no human supplied a review disposition.
