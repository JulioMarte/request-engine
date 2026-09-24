# P7 platform configuration, secrets and operational recovery — implementation handoff

Date: 2026-09-20  
Branch: `feature/platform-config-openbao-recovery`  
Baseline checkpoint before this handoff: `195ec7204aac75fa3699ffce7fca556e4f758e69`  
Authority: ADR 0015 + current guarantee inventory + current ownership/API/connection contracts  
Status: **implementation handoff; P7 is not delivered or production-certified**

> **Checkpoint 2026-09-23 — `feature/platform-config-openbao-recovery` @ `79b257fa`, PR #133 (draft).**
>
> Exact-head GitHub CI and Docker E2E are green. That only means the HEAD
> satisfies the gates that currently exist; it does **not** mean every
> P7-required gate has been created. Slice state:
>
> ```text
> P7-A ownership/capabilities/reconciliation   implemented
> P7-B governed DB read/command lifecycle      implemented
> P7-C HTTP metadata/configuration surface     implemented
> P7-D secret lifecycle/reconciliation         implemented; system/adversarial evidence incomplete
> P7-E SMTP typed validation/test/activation   implemented; TLS/AUTH protocol verified vs a real SMTP server; production-provider acceptance outstanding
> P7-F runtime resolver/hot reload/env cutover implemented; black-box hot-reload, poll convergence and SMTP-env-free managed delivery proven
> P7-G Communications integration              implemented
> P7-H OIDC administration                     pending
> P7-I signing key lifecycle                   partial: appointment-option key IDs + retiring-key verification overlap implemented; governed OpenBao-backed runtime keyring/rotation command pending
> P7-J readiness projection                    implemented for durable SMTP + deployment fence/secret-store/recovery-delivery/OIDC facts; backup/restore evidence awaits P7-K
> P7-K backup/restore/clone fencing            tooling implemented: encrypted PostgreSQL+OpenBao bundle, explicit schedule/retention, fenced restore evidence, clone fence proven; clean-environment restore drill + RPO/RTO acceptance pending
> ```
>
> Section 2 is the present-truth checkpoint for slice state. Sections 4-15 remain
> the unchanged acceptance obligations: an implemented slice is not a closed
> slice until its required evidence class exists.

## 0. Executive decision

P1-P6 are now the trust root. Do not reopen them merely because P7 needs
configuration.

P7 turns the private configuration/secret-store foundation into a governed
self-hosted administrative product surface:

```text
Platform Owner
  + current Platform authority
  + recent PHISHING_RESISTANT proof
        |
        v
governed platform-configuration commands
        |
        +--> PostgreSQL
        |      typed revisions
        |      lifecycle / audit facts
        |      active-version authority
        |
        +--> PlatformSecretStore
        |      reversible secret material
        |      OpenBao reference backend
        |
        +--> provider validation/test ports
        |
        +--> activation
               |
               +--> runtime resolver/cache
               +--> workers/providers observe new revision
               +--> no process restart
```

The target is **not** a generic settings table, a second IAM system, a second
worker engine, or a web UI. The admin UI can be built later over the same
canonical HTTP operations.

P7 is complete only when the application can govern operational configuration
and secret metadata through the Platform Owner trust root, runtime consumers can
adopt active revisions without restart, and the production recovery package has
been exercised rather than merely documented.

## 1. Current baseline that the next agent must preserve

The following are already delivered and must be treated as dependencies, not
work to reimplement:

- Instance Claim, setup closure, Platform Owner lifecycle and multi-owner
  continuity (P1-P5).
- Native HUMAN recovery posture, verified recovery addresses, governed two-HUMAN
  recovery, offline owner break-glass and async/fenced recovery delivery (P6,
  migrations through the current head).
- `PlatformSecretStore` in
  `src/request_engine/platform/secrets/platform_store.py`.
- `OpenBaoPlatformSecretStore` with KV-v2 CAS in
  `src/request_engine/platform/secrets/openbao_secret_store.py`.
- OpenBao production-oriented reference material under `deploy/openbao/`.
- Private configuration foundation from
  `0069_platform_configuration_foundation.py`:
  `platform_secret_bindings`,
  `platform_configuration_revisions`,
  `platform_configuration_facts`, immutable payload/binding identity,
  monotonic lifecycle and one-ACTIVE-revision-per-kind.
- Recovery worker fencing, async publication, retry/unknown semantics and worker
  supervision in the current worker runtime.
- Current exact-head evidence at the checkpoint above: GitHub CI and Docker E2E
  are green.

Do not rewrite accepted migrations. Discover the actual Alembic head before each
new migration and append from it.

## 2. Checkpoint: implemented slices vs open work

P7 is **not** delivered merely because OpenBao and revision tables exist. This
section is the present-truth checkpoint; it supersedes the original gap list and
must be read together with the checkpoint block in section 0.

Implemented and exercised in the current checkpoint:

1. Governed configuration command/read API over the 0069 tables (P7-B/P7-C).
2. Governed secret write/rotate/revoke API with a durable mutation ledger, exact
   backend version/CAS fencing and an explicit reconciliation state (P7-D).
3. SMTP staging, validation, provider test and activation through the control
   plane, with typed configuration and secret references, plus certificate-
   verifying implicit TLS and STARTTLS proven against a real SMTP server
   (`INV-SMTP-TRANSPORT-SECURITY-001`) (P7-E).
4. A revision-aware runtime resolver with cache fingerprint, LISTEN/NOTIFY
   invalidation and a periodic polling backstop; managed-over-bootstrap
   precedence (P7-F).
5. A real Communications webhook path that resolves the ACTIVE
   `communications.webhook` revision with exact revision pinning per delivery
   (P7-G).
6. A first diagnostic readiness projection exposing managed-SMTP facts (P7-J).
7. The reference worker composes `native_recovery_delivery` and
   `platform_configuration_invalidation` alongside `identity_recovery_delivery`,
   so exposing verified-address recovery cannot silently omit its worker stream
   (P7.0 prerequisite resolved).

Still open and required before the corresponding slice is complete:

- P7-D: adversarial real-OpenBao split-brain/concurrency evidence. The normative
  `INV-PLATFORM-SECRET-LIFECYCLE-001` guarantee and its unit-level
  reconciliation proofs now exist; the real-OpenBao adversarial run is still
  outstanding.
- P7-E: protocol conformance against a real RFC 5321 SMTP server (implicit TLS,
  STARTTLS, AUTH, delivery) now exists and passes in CI, and the client was
  fixed to verify the server certificate for implicit TLS. A controlled
  production SMTP provider acceptance (real DNS/TLS/AUTH/trottling) is still
  outstanding.
- P7-F: closed for the managed SMTP cutover contract. The black-box
  `platform-configuration` suite now starts control-plane/worker with no
  `REQUEST_ENGINE_SMTP_*` bootstrap settings, configures SMTP only through the
  governed P7 HTTP + OpenBao path, proves live worker delivery, rotates the secret
  and ACTIVE revision without restarting the worker, and the real-PostgreSQL
  missed-NOTIFY polling proof remains the correctness backstop.
- P7-J: the projection now composes durable SMTP state with explicit deployment
  facts for clone fencing, secret-store configuration, recovery-delivery source
  and native-only OIDC posture. Backup/restore evidence intentionally remains
  unknown until P7-K records real operational evidence. Owner-continuity and
  strong-auth posture remain candidates for a later diagnostic expansion, not
  blockers for the current P7 configuration readiness contract.
- P7-H: governed OIDC provider administration (no client secret while no current
  flow needs one).
- P7-I: appointment-option HMAC now has explicit active key IDs and
  retiring-key verification overlap at the codec boundary. Legitimate
  short-lived tokens survive rotation while the retiring key is accepted and
  fail once it is removed. Remaining work is the governed runtime keyring source
  and rotation/retirement command through the platform secret-store boundary.
  The identity-exchange fingerprint key is intentionally not treated as the same
  key family because it contributes to persisted equality fingerprints and
  requires an explicit migration strategy rather than blind replacement.
- P7-K: clone fencing is implemented fail-closed at production composition
  boundaries and proven black-box by the `clone-fence` Docker E2E suite: SMTP
  recovery and ordinary outbox traffic do not reach Mailpit/event-sink while
  fenced. Recovery tooling now creates one encrypted bundle containing a
  PostgreSQL custom-format dump plus OpenBao Raft snapshot, requires an off-host
  copy unless local-only mode is explicitly selected, verifies bundle membership
  and checksums, restores only while outbound-fenced, can emit restore-completion
  evidence only after both authoritative restore steps succeed, and can render a
  systemd timer with operator-selected schedule and local retention. The
  remaining P7-K acceptance gate is an exercised restore into a clean
  environment/host with post-restore Request Engine reads, governed secret
  resolution, offline owner recovery and clone-fence verification. Observed
  RPO/RTO must then be recorded and accepted; no value is invented by the repo.
- P7 observability: activation/validation/reconciliation/invalidation telemetry.

Do not infer P7 completion from a green exact-head; several required gates do not
exist yet.

## 3. Ownership decision before code

The current ownership map says `platform` owns **technical mechanics only**.
A product-level configuration lifecycle therefore must not be hidden under
`platform/` merely because the tables are installation-wide.

### Recommended owner

Create a narrow business module named `platform_configuration` **only after
recording the ownership change**.

It owns:

- installation-wide operational configuration revision semantics;
- configuration stage/validate/activate/disable commands;
- secret-binding metadata lifecycle as an administrative product capability;
- provider validation/test orchestration;
- platform configuration/readiness projections.

It does **not** own:

- secret-store HTTP mechanics (`platform/secrets`);
- worker/lease/fencing mechanics (`platform/worker`);
- SMTP delivery semantics (`communications`);
- identity/Platform Owner authority (`tenancy`);
- OIDC cryptographic verification mechanics (`platform/security`);
- business notification intent/delivery lineage (`communications`).

If maintainers reject a new module, stop and explicitly choose another business
owner before implementation. Do **not** default to `platform` or
`entrypoints/http`.

Introducing `platform_configuration` requires one coherent update to:

- `docs/10-module-ownership-map.md`;
- `docs/09-python-module-architecture.md`;
- `docs/13-connection-surfaces.md`;
- `docs/14-architecture-fitness-functions.md`;
- `tests/architecture/dependency_policy.py`;
- relevant documentation-contract rules.

This is P7.0, not optional cleanup.

## 4. Hard invariants for all P7 work

These invariants are non-negotiable:

### Configuration authority

- PostgreSQL is authoritative for which configuration revision is active.
- Configuration is typed; there is no generic arbitrary key/value mutation API.
- At most one revision per `configuration_kind` is ACTIVE.
- Validation must precede activation.
- Activation is serialized in PostgreSQL and rejects stale concurrent intent.
- An activation either supersedes the prior ACTIVE revision and activates the
  new revision atomically, or has no effect.
- LISTEN/NOTIFY is cache invalidation only; PostgreSQL remains truth.

### Secret authority

- Plaintext reversible secrets never live in ordinary PostgreSQL configuration,
  audit, outbox, logs, traces or admin responses.
- Human APIs may write/rotate/revoke but can never read plaintext back.
- Runtime-only resolution goes through `PlatformSecretStore`.
- Creation is create-if-absent; rotation requires exact expected backend
  version/CAS.
- A stale secret rotation fails closed.
- Secret binding metadata and backend secret mutation must not silently diverge.
- Network/provider I/O never occurs while authoritative PostgreSQL locks are
  held.

### Authentication/authorization

- Configuration/secret mutations require a HUMAN Platform actor.
- High-risk mutations require recent `PHISHING_RESISTANT` authentication.
- Recovery-restricted actors cannot perform authority-changing/high-risk
  configuration operations through a bypass.
- No `if Platform Owner then *` shortcut.
- No `platform.secret.read_plaintext` human capability.
- Caller-provided actor/principal/assurance values never establish authority.

### Provider semantics

- SMTP ambiguous post-transmission outcome is UNKNOWN and is not blindly
  republished.
- Validation/test I/O happens outside authoritative DB locks.
- A provider validation result may be committed only if the candidate revision
  is still the exact revision that was validated.
- Provider SDK types do not leak into module contracts.

### Recovery

- OpenBao/SMTP availability must never become a prerequisite for offline owner
  recovery.
- P7 must not reopen first-run setup.
- P7 must not add a universal recovery credential, root password or direct SQL
  product reset.
- Cloned/restored environments must not emit production side effects until
  explicitly unfenced.

## 5. Capability model

Add exact explicit Platform-plane capabilities rather than one
`platform.settings.manage` capability.

Recommended vocabulary:

| Capability | Type | Recent phishing-resistant proof |
| --- | --- | --- |
| `platform.configuration.read` | query | no |
| `platform.configuration.stage` | command | yes |
| `platform.configuration.validate` | command | yes |
| `platform.configuration.activate` | command | yes |
| `platform.configuration.disable` | command | yes |
| `platform.secret.write` | command | yes |
| `platform.secret.rotate` | command | yes |
| `platform.secret.revoke` | command | yes |
| `platform.provider.test` | command | yes |
| `platform.readiness.read` | query | no |

All mutation capabilities are Platform-plane, HUMAN-only operational authority
and should be classified as high-risk/authority-sensitive so the existing
freshness and recovery-posture guards apply. Do not project secret/config
mutation operations as public agent tools by default.

The initial Platform Owner policy must be evolved deliberately if these
capabilities are to be granted by default. Do not mutate an immutable policy
catalog in place; use the repository's existing controller-policy evolution
pattern and prove continuity.

## 6. Target API surface

Names may change to comply with current API standards, but one canonical HTTP
operation must exist per semantic operation. Do not build a second admin-only
implementation behind a CLI.

Recommended surface:

```text
GET  /v1/platform/configurations
GET  /v1/platform/configurations/{configuration_kind}
GET  /v1/platform/configurations/{configuration_kind}/revisions/{revision}

POST /v1/platform/configurations/{configuration_kind}/revisions
POST /v1/platform/configurations/{configuration_kind}/revisions/{revision}:validate
POST /v1/platform/configurations/{configuration_kind}/revisions/{revision}:activate
POST /v1/platform/configurations/{configuration_kind}/revisions/{revision}:disable

POST /v1/platform/secrets
POST /v1/platform/secrets/{binding_id}:rotate
POST /v1/platform/secrets/{binding_id}:revoke
GET  /v1/platform/secrets/{binding_id}

POST /v1/platform/providers/{configuration_kind}/{revision}:test

GET  /v1/platform/readiness
```

Administrative secret reads return metadata only, for example:

```json
{
  "binding_id": "...",
  "purpose": "email.smtp.password",
  "backend": "openbao",
  "configured": true,
  "backend_version": 4,
  "revision": 7,
  "last_rotated_at": "...",
  "status": "active"
}
```

Never include the original secret value, secret-store token, backend path or
recovery proof.

Use revision/precondition semantics for every mutation. If current API standards
require `expected_revision` in the body rather than headers, follow that
existing convention consistently.

## 7. P7 implementation sequence

### P7.0 — Reconcile current head and ownership

Before product changes:

1. Verify actual branch/PR/Alembic head and exact-head CI.
2. Reconcile documentation statements that still say P5 is pending.
3. Record the `platform_configuration` ownership decision or another explicit
   owner.
4. Update dependency policy/ownership docs atomically.
5. Verify `reference_worker_factory` composes both governed and Native recovery
   delivery streams when recovery delivery is configured.
6. Add/strengthen an architecture/composition test proving that a deployment
   exposing verified-address recovery cannot silently omit its worker.
7. Inventory every current deployment/env-based SMTP, Vault/OpenBao, OIDC,
   signing-key and provider configuration consumer. The output of this inventory
   defines the cutover set; do not guess from environment variable names alone.

**Exit:** one owner, one dependency shape, no hidden missing worker stream, and a
written inventory of configuration consumers.

### P7.1 — Governed DB command/read boundary

Append a migration from the actual current head. Reuse 0069 tables; do not create
a parallel configuration store.

Add narrow SECURITY DEFINER functions/read surfaces for:

- list/read configuration revision metadata;
- stage a typed revision;
- mark exact draft revision validated;
- atomically activate exact validated revision and supersede old ACTIVE;
- disable an allowed draft/validated/active revision;
- create binding metadata only after secret-store create succeeds;
- commit exact backend version after rotation;
- revoke binding metadata after backend revocation succeeds or through an
  explicitly documented degraded reconciliation state.

Every command must:

```text
READ actor provenance
PLAN
LOCK serialization root
VALIDATE capability/current revision/current state
WRITE
EMIT append-only fact
COMMIT
```

Activation should lock by `configuration_kind` before revision rows. The
concurrent loser must receive a deterministic conflict; unique-index violation
alone is not the product error contract.

Add idempotency/request fingerprinting using the repository's existing pattern.
A repeated key with identical intent returns the original result; same key with
different intent conflicts.

**Required DB proofs:** lifecycle, stale revision, concurrent activation, exact
one ACTIVE, replay/idempotency conflict, append-only facts, direct-role denial,
PUBLIC EXECUTE denial and reviewed function ownership/search_path.

### P7.2 — Capability and HTTP product surface

Add the capability definitions from section 5 and a module-owned router under
the selected P7 owner.

Composition happens in `platform_control_app.py`; business semantics do not.

All mutation handlers must require:

- authenticated Platform HUMAN;
- exact capability;
- current authority revision if that capability uses revision fencing;
- recent phishing-resistant proof;
- normal recovery posture.

Reads return metadata/projections only.

Add stable typed errors such as:

```text
platform_configuration_not_found
platform_configuration_revision_conflict
platform_configuration_state_conflict
platform_configuration_validation_required
platform_configuration_provider_invalid
platform_secret_conflict
platform_secret_unavailable
platform_secret_not_found
platform_provider_validation_failed
platform_provider_test_unknown
```

Do not echo provider credentials or backend errors containing sensitive
material.

**Exit:** configuration/secret metadata can be governed over HTTP without any
runtime consumer change yet.

### P7.3 — Secret administration orchestration

Implement a product service that coordinates
`PlatformSecretStore` + PostgreSQL metadata without holding DB locks across
network I/O.

#### Create

```text
authorize + validate request
  -> allocate opaque secret_id
  -> PlatformSecretStore.write(expected_version=None)
  -> authoritative DB command records binding metadata/version
  -> on DB failure, best-effort revoke only the secret created by this call
```

#### Rotate

```text
read exact binding metadata/revision
  -> store.write(secret_id, new value, expected_backend_version)
  -> DB command CASes exact old binding revision/backend version
  -> if DB commit loses a race, do NOT invent metadata;
     reconcile backend metadata and surface an operator-visible conflict
```

The rotation design needs special care because backend CAS may succeed before
the DB metadata CAS loses. The implementation must provide a deterministic
reconciliation path; pretending the operation is atomic across PostgreSQL and
OpenBao is incorrect.

Recommended approach: add a short-lived durable secret-mutation operation record
with states such as `prepared/backend_applied/committed/reconcile_required`
rather than trying to emulate a distributed transaction. The record contains no
plaintext. A retry with the same idempotency key reconciles backend metadata and
finishes or reports an explicit conflict.

#### Revoke

Backend destruction is irreversible. Require exact binding revision plus recent
phishing-resistant proof. If OpenBao succeeds and the DB commit fails, persist or
reconcile to a state that cannot continue to present the binding as healthy.
Never silently reactivate a backend-deleted binding.

**Exit:** no plaintext read API, exact backend CAS, durable cross-system
reconciliation and adversarial tests for DB/OpenBao split-brain cases.

### P7.4 — SMTP as the first typed configuration provider

Define a typed SMTP configuration contract, not arbitrary JSON accepted from
clients.

At minimum validate:

- host;
- port;
- transport security mode;
- connect/auth timeouts;
- username/from identity as applicable;
- secret binding purpose/type;
- optional HELO/server-name semantics if supported.

Never place the password in the configuration JSON.

Provider lifecycle:

```text
stage config + bind secret
        |
        v
validate candidate
  DNS/TCP/TLS/AUTH/provider-specific checks
  outside DB locks
        |
        v
commit VALIDATED only if exact candidate revision is still DRAFT
        |
        +--> optional explicit test message
        |
        v
activate exact VALIDATED revision
```

Validation must distinguish invalid configuration from temporary provider
unavailability.

A test mail is not activation. Its result is an append-only provider-test fact.
Ambiguous SMTP outcome is UNKNOWN.

Do not add IMAP merely to satisfy validation; ADR 0015 does not require it.

**Tests:** fake/boundary SMTP for deterministic unit/E2E plus at least one
production-acceptance run against a real controlled SMTP endpoint before D6 is
certified.

### P7.5 — Active runtime resolver and hot reload

Create a technical resolver contract consumed by workers/runtime providers:

```text
ActivePlatformConfigurationResolver
  read active PostgreSQL revision
  -> typed provider config
  -> secret binding metadata
  -> PlatformSecretStore.resolve() only in trusted runtime
```

Cache by something equivalent to:

```text
(configuration_kind, active_revision, secret_binding_revision)
```

Activation emits PostgreSQL NOTIFY after the authoritative write. Runtime
processes invalidate matching cache entries. A periodic revision poll reconciles
missed notifications.

Hard rule:

```text
LISTEN/NOTIFY = acceleration
PostgreSQL active revision = truth
```

A process restart must not be required for an activated SMTP change.

#### Environment cutover

Avoid permanent split brain between environment variables and PostgreSQL.

Recommended transition:

- bootstrap/environment values may remain only when no ACTIVE product-managed
  revision exists;
- once an ACTIVE revision exists for a configuration kind, that revision wins;
- expose the source in readiness: `bootstrap` vs `managed`;
- provide a deliberate migration/import path if operators want to move existing
  env configuration into P7;
- never silently copy secrets from environment into OpenBao.

The final P7 DoD requires recovery delivery to operate from active managed SMTP
configuration without SMTP credentials in the Request Engine process
environment.

### P7.6 — Communications/notification integration

Do not move communication business truth into `platform_configuration`.

`communications` continues to own:

- Notification/Communication intent;
- task/delivery lineage;
- provider outcome semantics;
- templates that carry business communication meaning.

P7 publishes a narrow typed configuration/provider resolver that
`communications` consumes.

If notification templates become product-configurable, define which fields are
installation policy versus business/tenant content before persistence. Do not
create one global arbitrary template store.

Business transactions produce durable intent/outbox work. They do not open SMTP
connections.

**Exit:** at least one real Communications path resolves active provider config
through P7 and preserves existing retry/UNKNOWN semantics.

### P7.7 — OIDC administration

OIDC remains optional.

Inventory the existing OIDC authority model first. Do not replace existing
cryptographic verification or IdentityBinding semantics.

Add governed administration for provider metadata actually needed by the
current verifier:

- issuer;
- audience/resource identifier;
- JWKS discovery/static endpoint policy;
- enabled/disabled state;
- client credentials only if a current flow requires them.

Any reversible provider credential uses a `PlatformSecretStore` binding.
Ordinary authority/configuration tables store references only.

Provider activation requires validation outside DB locks and exact revision
commit afterward.

Disabling or replacing an OIDC provider must not delete Principals or fabricate
authority. Existing native access remains independent.

### P7.8 — Signing keys/keyrings

Do this only after an inventory identifies current signing-key consumers.

Do not build an unused generic HSM/key-management framework.

For each required key family define:

- key purpose;
- active key ID;
- verification overlap/retirement window;
- rotation command;
- rollback/compromise semantics;
- where public verification material lives;
- where private material lives through the secret-store boundary.

Rotation must permit verification of artifacts legitimately signed by a retiring
key for their accepted lifetime. Never replace a signing key blindly because an
admin clicked “rotate”.

### P7.9 — Platform readiness projection

Add a read-only projection such as `GET /v1/platform/readiness`.

It may report facts like:

```text
platform_owner_continuity
owner_phishing_resistant_auth
offline_recovery_material_status (never the code)
secret_store reachable/unavailable
smtp bootstrap/managed/unconfigured
smtp active revision
smtp last validation
recovery_delivery worker configured
oidc optional/configured
backup evidence present/unknown
restore drill unknown/ready
clone fence state
```

This projection is diagnostic only. It grants no authority and must not become
the source of underlying truth.

### P7.10 — Backup, restore and clone fencing

This phase cannot be completed by unit tests alone.

Required production-oriented deliverables:

#### PostgreSQL

- automated backups with explicit schedule and retention;
- encrypted off-host copy;
- restore command/runbook;
- restore verification against a new database/host;
- evidence of migration/readiness after restore.

#### OpenBao

- automated Raft snapshots for the sealed/Raft production topology;
- encrypted off-host copy;
- retained unseal/recovery shares stored separately from the snapshot;
- restore into a fresh OpenBao instance;
- recreate policy/AppRole/Proxy machine credentials;
- verify existing PostgreSQL secret references resolve after restore.

#### Clone fencing

A production database/OpenBao clone to staging must start with outbound providers
fenced.

Do not use hostname detection.

Persist or inject an explicit environment/clone fence that blocks at least:

- SMTP;
- webhooks;
- provider callbacks/publishers that could contact production;
- any other external side-effect channel discovered in P7.0.

Unfencing is an explicit authenticated operator action/procedure after
environment-specific secret/provider rebinding.

#### Recovery drills

Exercise independently:

1. OpenBao + SMTP unavailable; Platform Owner recovers with offline code.
2. PostgreSQL restore with claimed Instance remains claimed.
3. OpenBao Raft restore resolves existing references.
4. Full-host rebuild from documented recovery package.
5. Production clone boots fenced and cannot send external side effects.

Record RPO/RTO observed during the drill. Do not invent acceptable RPO/RTO
values; they require operator/product acceptance.

## 8. Recommended PR / implementation slicing

Do not implement P7 as one enormous PR.

Recommended order:

```text
P7-A  ownership + capabilities + current-head reconciliation
P7-B  governed DB read/command lifecycle
P7-C  HTTP metadata/configuration surface
P7-D  secret mutation orchestration + reconciliation
P7-E  SMTP typed validation/test/activation
P7-F  runtime resolver + cache + hot reload + env cutover
P7-G  Communications integration
P7-H  OIDC administration
P7-I  signing-key inventory/rotation where required
P7-J  readiness projection
P7-K  backup/snapshot/restore/clone-fencing operational acceptance
```

After each slice:

- exact-head Python quality/architecture must pass;
- current-product must pass;
- affected guarantee/proof-map entries must have no execution gap;
- Docker E2E must stay green;
- update current docs in the same change.

Do not stack multiple failed slices and debug them simultaneously.

## 9. Required new/updated guarantees

Do not add a guarantee before corresponding behavior and executable proof exist.

The existing `INV-PLATFORM-SECRET-STORE-001` and
`INV-PLATFORM-CONFIG-REVISION-001` remain foundations.

Add guarantees equivalent to the following as slices become real:

```text
INV-PLATFORM-CONFIG-GOVERNANCE-001
  Platform configuration mutation requires explicit Platform HUMAN authority,
  recent phishing-resistant proof, exact revision/idempotency and append-only
  provenance.

INV-PLATFORM-CONFIG-ACTIVATION-001
  validation precedes activation; concurrent/stale activation cannot produce two
  active revisions; prior ACTIVE is superseded atomically.

INV-PLATFORM-SECRET-LIFECYCLE-001
  human APIs never replay plaintext; create/rotate/revoke are version safe;
  cross-system partial failure is explicitly reconcilable.

INV-PLATFORM-CONFIG-HOT-RELOAD-001
  runtime consumers converge on PostgreSQL ACTIVE revision without restart;
  notifications are optimization, periodic reconciliation is the backstop.

INV-SMTP-CONFIGURATION-001
  staged SMTP configuration validates outside DB locks, test result is distinct
  from activation, credentials are secret references and ambiguous send outcome
  is not blindly retried.

INV-SMTP-TRANSPORT-SECURITY-001
  implicit TLS (SMTPS) and STARTTLS verify the server certificate chain and
  hostname before credentials/message content are sent; a certificate that
  fails verification is a definitive security failure, never silently accepted.

INV-PLATFORM-CLONE-FENCE-001
  restored/cloned non-production environments cannot emit external side effects
  until explicitly unfenced.

INV-PLATFORM-DISASTER-RECOVERY-001
  documented recovery package can restore PostgreSQL/OpenBao authority state and
  preserves independent offline human access recovery.
```

Map every critical guarantee to real PostgreSQL/adversarial/HTTP or system
evidence as appropriate.

## 10. Test matrix

At minimum the completed program needs these evidence classes.

### PostgreSQL invariants

- exactly one ACTIVE revision per kind;
- lifecycle monotonicity;
- exact stale-revision rejection;
- deterministic concurrent activation winner;
- idempotency exact replay / key-reuse conflict;
- append-only configuration facts;
- direct table privilege denial;
- reviewed definer function owner/search_path/PUBLIC grants;
- secret binding version/revision monotonicity.

### Secret-store contract

- OpenBao create-if-absent;
- stale CAS rotation conflict;
- metadata without plaintext;
- revoke;
- unavailable/malformed backend mapping;
- no token/value leakage in exceptions;
- DB failure after backend write;
- backend success + DB CAS loss reconciliation;
- retry after ambiguous local failure.

### HTTP/security

- read capability boundaries;
- every mutation requires recent phishing-resistant HUMAN proof;
- recovery-restricted actor cannot mutate;
- stale authority revision fails;
- no secret plaintext appears in response/error/OpenAPI examples;
- recovery endpoints continue working with config store unavailable where
  independence is required.

### SMTP/provider

- invalid TLS/auth rejected without state activation;
- transient provider outage distinguishable from invalid configuration;
- exact candidate validated before state change;
- test-send success/failure/UNKNOWN recorded separately;
- activation after validation;
- stale candidate cannot be activated;
- active revision switches runtime provider without restart.

### Concurrency

- two stage requests for same next revision;
- two activations for one kind;
- rotate same secret from two operators;
- activation racing disable;
- runtime resolver observing activation while another process misses NOTIFY;
- provider validation result racing candidate disable/new revision.

### System / black-box

Extend the existing Docker suite registry rather than copying Compose/workflows.

Required journeys:

```text
fresh claim
 -> owner strong login
 -> create secret
 -> stage SMTP
 -> validate
 -> activate
 -> worker sends using managed config
 -> rotate secret
 -> worker adopts new secret without restart

recovery:
managed SMTP/OpenBao outage
 -> offline owner recovery still succeeds

clone:
restore/clone starts fenced
 -> outbound provider call is rejected before network I/O
```

Production restore drills are separate from ordinary CI where real sealed
OpenBao/off-host storage is required.

## 11. Observability

P7 must emit useful operational telemetry without secrets.

Metrics/traces/logs should answer:

- current active revision per configuration kind;
- validation success/failure/unavailable counts;
- activation/disable counts;
- secret rotation/reconciliation failures;
- cache invalidations and revision-poll corrections;
- provider configuration source: bootstrap vs managed;
- worker failures caused by unavailable configuration/secret store;
- backup/snapshot age;
- last successful restore drill timestamp/evidence reference;
- clone-fence state.

Never log secret value, recovery code, OpenBao token, SMTP password or raw
authentication proof.

Audit facts and telemetry are distinct. Logs are not the audit store.

## 12. Migration and rollout rules

- Append migrations only; do not modify 0069 or accepted recovery migrations.
- Use expand -> migrate -> contract if environment-based and managed
  configuration coexist during rollout.
- Do not delete environment bootstrap support until the managed path has
  production acceptance and an explicit retirement criterion.
- Do not allow both sources to remain ambiguous forever: managed ACTIVE
  configuration must have deterministic precedence.
- Every schema write surface requires lock root/order, idempotency, privileges,
  provenance and concurrent-loser semantics.
- Any new worker queue must use existing worker supervision/fencing rather than a
  second scheduler framework.

## 13. Decisions requiring operator/product input

Implementation must stop rather than invent these values:

- accepted ownership name if `platform_configuration` is rejected;
- production SMTP endpoint/account used for real provider acceptance;
- whether SMTP test messages require an operator-supplied destination;
- backup target/provider;
- backup retention;
- snapshot frequency;
- encryption/key custody for off-host backups;
- acceptable RPO/RTO;
- clone/unfence operational approval procedure;
- which signing-key families actually require P7 rotation;
- which optional OIDC providers/flows are in the supported production scope.

These are not reasons to block P7-A through P7-G. They are blockers for the
corresponding provider/production-certification slice only.

## 14. Explicit anti-patterns / stop conditions

Stop the implementation if the proposed change requires any of the following:

- generic `settings(key, value)` table;
- storing SMTP/OIDC/signing secret plaintext in PostgreSQL;
- admin plaintext secret read endpoint;
- permanent OpenBao root/static token in Request Engine;
- provider network I/O while authoritative DB locks are held;
- changing an ACTIVE configuration JSON in place;
- activation without a prior exact validation;
- one broad `platform.admin` or `platform.settings.*` bypass;
- silently granting all P7 capabilities merely because someone is a Platform
  Principal;
- using `platform/` as a business module to avoid an ownership decision;
- creating a second worker/retry engine;
- trusting LISTEN/NOTIFY as authoritative state;
- blind retry of UNKNOWN SMTP delivery;
- automatic setup reopening during recovery;
- automatic instance reset because hostname/environment changed;
- declaring disaster recovery complete without a restore drill;
- declaring P7 complete while SMTP still requires process-environment
  credentials for the managed runtime path.

## 15. Definition of Done

P7 is complete only when all applicable items below are demonstrated on the
same accepted source state.

### Product

- Platform Owner can list/read configuration metadata.
- Authorized Platform HUMAN can stage/validate/activate/disable typed revisions.
- Authorized Platform HUMAN can create/rotate/revoke secrets without plaintext
  replay.
- SMTP can be configured, validated, test-sent and activated through control
  plane HTTP.
- Runtime/worker adopts activated SMTP without restart.
- Managed recovery delivery works without SMTP credentials in the process
  environment.
- Optional OIDC administration is governed if included in supported scope.
- Required signing-key families have explicit safe rotation if included after
  inventory.
- Readiness reports true underlying state and is not an authorization source.

### Security

- all high-risk mutations require recent phishing-resistant HUMAN proof;
- recovery-restricted actors cannot perform P7 mutations;
- PostgreSQL contains only non-secret config and opaque secret metadata;
- no human plaintext secret read operation exists;
- OpenBao CAS/version semantics are enforced;
- least-privilege runtime/control/worker roles remain distinct;
- configuration/secret changes are append-only auditable;
- no universal admin/backdoor is added.

### Concurrency/failure

- activation is deterministic and single-winner;
- stale activation fails;
- cross-system secret mutation partial failure is reconcilable;
- missed cache notification self-heals by revision polling;
- ambiguous provider send is not blind-retried;
- worker crash/restart preserves fenced semantics.

### Operations

- OpenBao production topology is sealed/Raft, not dev mode;
- PostgreSQL backups are automated;
- OpenBao snapshots are automated;
- encrypted off-host copies exist;
- restore is executed into a clean environment;
- clone starts provider-fenced;
- full recovery package is documented and tested;
- observed RPO/RTO is recorded and accepted by the operator/product owner.

### Evidence

- new DB invariant/adversarial/concurrency tests run in current-product;
- HTTP E2E covers governed config and secret lifecycle;
- Docker black-box journey covers managed SMTP hot reload;
- OpenBao adapter tests remain green;
- guarantee/proof-map validation reports no gaps;
- exact-head CI is green;
- exact-head Docker E2E is green;
- real-environment provider/restore evidence exists for claims ordinary CI cannot
  prove.

## 16. First actions for the receiving agent

Start with reconnaissance, not implementation:

```text
1. Verify current branch/PR/HEAD and Alembic head.
2. Run/read exact-head CI and Docker E2E evidence.
3. Read ADR 0015, this handoff, current-guarantees, ownership map, docs 07/13/15/16.
4. Inspect 0069 effective schema and all callers of PlatformSecretStore.
5. Inventory every SMTP/OpenBao/Vault/OIDC/signing-key environment consumer.
6. Verify reference worker wiring for native_recovery_delivery.
7. Propose/record the P7 business owner and dependency-policy change.
8. Implement only P7-A/P7-B first.
9. Keep exact-head green before proceeding to P7-C.
```

Do not begin with SMTP UI, hot reload or backup automation. If the governed
configuration command boundary is wrong, every later slice will build on the
wrong authority model.

## 17. Final handoff statement

The trust root is intentionally considered closed at P6. P7 consumes it.

The next agent should treat the existing recovery work as a security dependency,
not as unfinished scaffolding. The difficult work in P7 is not “saving settings”;
it is making PostgreSQL configuration authority, OpenBao secret authority,
provider I/O, runtime hot reload and production recovery coexist without split
brain or a new privileged bypass.

If an implementation makes those boundaries less explicit in exchange for fewer
files or fewer steps, it is probably moving in the wrong direction.
