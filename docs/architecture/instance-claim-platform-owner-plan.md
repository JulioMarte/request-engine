# Instance claim, Platform Owner and administrative trust-root plan

Date: 2026-09-18  
Branch of reference: `cohesion/system-optimization`  
Status: **accepted architecture and implementation handoff; not implemented and not production certification.**

ADR 0014 is the decision authority for the trust-root change. This document is
the executable design/handoff. It deliberately separates accepted semantics from
proposed implementation names so implementation can change private structure
without weakening guarantees.

## 0. Executive decision

Request Engine will behave like a modern self-hosted product:

```text
fresh installation
      ↓
first-run setup
      ↓
first successful finalized human claim
      ↓
Platform Owner
      ↓
setup closes permanently
      ↓
all later platform users are invited/provisioned
```

This does **not** mean `if users == 0: superuser = true`.

The authoritative design is:

```text
durable Instance state
        +
bounded ephemeral SetupSession
        +
native authentication enrollment
        +
mandatory WebAuthn user verification
        +
single-use recovery material
        +
one atomic final claim
        +
normal platform Principal/capability model
```

The future administrative UI will consume the same control-plane HTTP API that
system/E2E tests use. There is no private CLI business path in the target state.

## 1. Goals

The implementation must provide all of the following simultaneously:

1. self-hosted first-run UX comparable to n8n/Portainer/Coolify-style ownership;
2. no permanent superuser bypass;
3. first-owner establishment fully testable through real HTTP/TCP;
4. PostgreSQL-enforced exactly-one first claim under concurrency;
5. no partially effective owner if setup is abandoned halfway;
6. phishing-resistant authentication for Platform Owners;
7. explicit authentication assurance and step-up semantics;
8. setup permanently closed after claim;
9. emergency recovery that never reopens first-run setup;
10. later multiple Platform Owners/Admins through governed operations;
11. compatibility with Request Engine's Principal/binding/capability model;
12. future UI, automation and SDK clients without a second execution path.

## 2. Non-goals for the first implementation

Do not expand scope by simultaneously building:

- the final admin frontend;
- billing/Stripe;
- tenant payment-to-provisioning automation;
- full SAML/B2B IdP administration;
- adaptive behavioral-risk scoring;
- device fingerprinting;
- HSM-specific attestation policy;
- a generic "configuration platform" for every environment setting;
- a generic IAM framework detached from Request Engine's current identity model.

The trust root should finish before those features consume it.

## 3. Current baseline that must be reconciled, not duplicated

Current HEAD already has useful pieces:

- separate `platform_control_app.py`;
- separate least-privilege auth/read/write DB pools in `platform_server.py`;
- native identity/password/session lifecycle;
- session `authenticated_at` and a five-minute recent-authentication mechanism;
- platform Principal resolution and explicit capabilities;
- platform continuity predicate and topology lock discipline;
- governed recovery cases;
- Vault secret-store adapter and SMTP delivery channel;
- immutable initial tenant-controller policy catalog;
- reusable Docker/TCP system-E2E platform.

Current pieces that are **transitional** under ADR 0014:

- `entrypoints/platform_bootstrap_cli.py`;
- operator-only bootstrap DSN as canonical installation path;
- bootstrap intent token ceremony as the canonical first-owner product journey;
- password-only definition of an authenticatable native platform controller;
- open native identity enrollment mounted wholesale on the control plane;
- `tenant-controller-v3` default while newer immutable policies exist.

Do not build the new design beside these and leave both authoritative.

## 4. Ownership and module boundaries

### 4.1 Installation/instance lifecycle

Installation claim is platform-level product policy, not a generic security
utility. Its durable Instance/claim semantics need one explicit owner.

Recommended ownership: **tenancy/platform administration capability within the
current tenancy owner**, because it creates the platform Principal/binding/grants
and already owns platform provisioning authority.

Do not put Instance business policy in `platform/security`. That package may own
cryptographic/authentication mechanics, not "who owns this Request Engine
installation".

If implementation analysis proves a distinct bounded context is warranted, that
is an explicit architecture decision; do not create `modules/instance` merely
for folder symmetry.

### 4.2 Authentication

`platform/security` owns technical native authentication mechanics:

- password hashing/verification;
- WebAuthn challenge/verification mechanics;
- session credentials;
- assurance/freshness evidence;
- opaque setup-session token mechanics if kept technical.

The business command that turns completed authentication enrollment into platform
authority remains owned by the platform/tenancy capability.

### 4.3 Secrets

Raw TOTP seeds, recovery delivery secrets and provider credentials do not become
ordinary business columns. Use the existing secret-store boundary where
reversibility is required.

WebAuthn server state stores public credential material, never authenticator
private keys.

Recovery codes are digest-only and never need reversible storage.

## 5. Durable data model

Names below are proposed; invariants are normative.

### 5.1 Platform Instance

A singleton durable fact/table must exist independently of users.

Conceptual fields:

```text
platform_instance
  id uuid primary key
  state enum/text: unclaimed | claimed
  revision bigint > 0
  created_at timestamptz
  claimed_at timestamptz nullable
  initial_owner_principal_id uuid nullable
  claim_provenance text nullable
```

Required constraints:

- exactly one authoritative Instance row per Request Engine database;
- `UNCLAIMED`: no `claimed_at`, no initial owner;
- `CLAIMED`: `claimed_at` and owner are present;
- state transition is one-way;
- identity columns are immutable;
- deleting users/Principals/credentials never changes Instance state;
- restore preserves Instance ID and state.

Do not infer claim status from Principal count.

### 5.2 SetupSession

Conceptual fields:

```text
setup_sessions
  id uuid
  token_digest bytea
  token_fingerprint text
  status pending | consumed | expired | revoked
  revision bigint
  created_at
  expires_at
  consumed_at nullable
  mode interactive | protected | automated
  idempotency/provenance metadata
```

Security requirements:

- random secret >= 256 bits;
- raw secret returned once only;
- digest only at rest;
- constant-time verification;
- TTL default proposal: 20 minutes;
- no refresh;
- bounded number of active sessions; a new session need not invalidate another,
  because final claim serialization determines the winner;
- setup session authorizes only setup operations;
- after Instance is CLAIMED, creation/consumption fails closed.

Do not make SetupSession a normal `native_session`.

### 5.3 Pending enrollment material

Do **not** create an effective platform Principal early.

The preferred design is explicit **SetupSession-owned pending enrollment
material**, promoted atomically during finalization. This avoids allowing
unauthenticated abandoned setup attempts to reserve the permanent native-login
namespace, create durable credential litter or force cleanup semantics onto the
ordinary identity lifecycle.

Conceptually the pending material may contain:

```text
setup_pending_identity
  setup_session_id
  normalized_login_handle
  password_verifier/version when password is used
  stable non-PII WebAuthn user_handle
  timestamps/revision

setup_pending_webauthn_credential
  setup_session_id
  credential_id
  public credential material
  verified registration facts
```

Pending rows are not Principals, bindings, grants or normal native identities and
cannot authenticate on ordinary native login endpoints.

On successful finalization, one transaction creates/promotes the permanent
native identity/credentials/authenticators and the platform authority facts. On
expiry/revocation, pending material is safely garbage-collectable without
rewriting identity history.

Creating an ordinary native identity before finalization is permitted only if an
implementation review proves all of the following: abandoned setup cannot
permanently squat login handles, cleanup has explicit safe semantics, rate limits
bound durable-row creation, and no ordinary authentication path becomes usable
before claim. This is no longer the preferred path.

Do not invent a third hidden authority type.

### 5.4 Built-in identity authorities and the fresh-install chicken-and-egg

The current CLI silently performs another bootstrap responsibility: it discovers
or creates the canonical native and workload identity-authority rows. ADR 0014
cannot remove the CLI while leaving that responsibility implicit.

A clean Request Engine database therefore needs **built-in authority identity
facts established independently of the human claim**.

Recommended target:

```text
Platform Instance
  ├── built_in_native_authority_id
  └── built_in_workload_authority_id
```

The migration/instance-initialization path should:

1. find an existing canonical `native / request-engine-native` authority and
   `workload / request-engine-workload` authority when upgrading a database that
   already used the old bootstrap;
2. fail closed on ambiguous/conflicting canonical rows rather than guessing;
3. create the missing built-in authority rows on a truly fresh database;
4. bind their IDs to the Instance durable state;
5. preserve those IDs on backup/restore;
6. never derive authority identity from caller input.

The control-plane/runtime should read the built-in native authority from this
trusted durable installation state rather than requiring a human to copy the UUID
printed by a bootstrap CLI into environment configuration.

This change needs an explicit migration and startup-compatibility plan. Do not
delete `REQUEST_ENGINE_*_IDENTITY_AUTHORITY_ID` configuration until all callers,
tests and upgrade paths have been inventoried and migrated.

The built-in workload authority is not permission to create workloads; it is only
the authentication authority used later by governed workload provisioning.

### 5.5 WebAuthn credentials

Conceptual durable fields:

```text
webauthn_credentials
  credential_id bytes/text unique
  native_identity_id uuid
  public_key / COSE key
  sign_count
  aaguid nullable
  transports nullable
  backup_eligible
  backup_state
  user_verification policy/result metadata
  status active | revoked
  created_at
  last_used_at
  revision
```

Rules:

- Relying Party ID and allowed origins come from trusted deployment/configuration;
- registration and authentication challenge are random, short-lived and
  single-purpose;
- verify challenge, RP ID hash, origin, ceremony type and signature;
- `userVerification = required` for Platform Owner setup and privileged step-up;
- private key/biometric/PIN never reaches or is stored by Request Engine;
- attestation SHOULD default to privacy-preserving `none` unless a future
  hardware-policy requirement explicitly needs attestation;
- sign-count handling must follow WebAuthn semantics and must not create false
  lockouts for authenticators whose counters are zero/non-global;
- credential deletion/revocation is governed and auditable.

Use WebAuthn Level 3 semantics, not ad-hoc "passkey JSON".

### 5.6 TOTP

TOTP is fallback/secondary, not phishing-resistant assurance.

If implemented:

```text
totp_authenticator metadata in DB
secret_reference -> secret store
status/revision/timestamps
```

Never store raw seed in ordinary PostgreSQL columns or logs.

Enrollment requires proof of one valid TOTP after seed issuance.

### 5.7 Recovery codes

Conceptual fields:

```text
recovery_code_set
  id
  native_identity_id
  version
  status
  created_at

recovery_code
  set_id
  code_digest
  used_at nullable
```

Rules:

- generate cryptographically random high-entropy codes;
- display plaintext only once;
- store digests only;
- each code is single use;
- rotating/regenerating codes invalidates remaining prior codes;
- use of a code emits a security audit event and should force security review /
  re-enrollment before high-risk authority changes;
- a recovery code alone does not satisfy phishing-resistant step-up;
- a UI acknowledgement that codes were displayed/saved is UX state, not proof
  that the human actually stored them safely; security must not depend on such an
  acknowledgement.

## 6. Setup state machine

Recommended product-visible flow:

```text
Instance UNCLAIMED
    |
    v
Create SetupSession
    |
    v
Establish native identity credential
    |
    v
Register + verify WebAuthn credential
    |
    v
Generate/acknowledge recovery codes
    |
    v
Finalize claim
    |
    +-- transaction loses race --> conflict, no authority
    |
    v
Platform Owner effective
Instance CLAIMED
```

The server must derive readiness from durable facts. The client does not submit
"security_complete=true".

The finalize preconditions include at minimum:

- Instance still UNCLAIMED;
- SetupSession valid and unconsumed;
- native identity active under configured native authority;
- at least one active verified WebAuthn credential satisfying Platform Owner
  policy;
- required recovery material created/acknowledged according to the chosen UX;
- no existing effective platform owner created by another winner;
- immutable `platform-owner-v1` policy exists.

## 7. Claim modes

### 7.1 Interactive

Normal self-host experience.

The unauthenticated setup surface exists only while Instance is UNCLAIMED and only
on the control-plane app.

### 7.2 Protected interactive

A deployment-provided secret/proof gates SetupSession creation.

The proof is deployment bootstrap material, not a future user credential.

Requirements:

- secret supplied via mounted secret/file or comparable secret mechanism where
  practical;
- digest/constant-time verification;
- never persist raw proof in Request Engine DB/logs;
- after claim it has no power;
- changing/removing it after claim does not affect owner login.

### 7.3 Automated

Automation may create the SetupSession, preconfigure non-secret installation
inputs and drive every machine-safe HTTP step, but **automation does not get to
fabricate a human Platform Owner's phishing-resistant authenticator**.

For the normal HUMAN-owner model, final activation still requires a human to
complete a real WebAuthn ceremony. A deployment can therefore automate up to the
point where the owner opens the one-time setup flow and registers a passkey.

A fully unattended deployment that needs immediate machine administration must
use a separately designed bounded Platform INTEGRATION/service Principal after
the trust root exists; it must not create a fake HUMAN with a CI-owned passkey.

Importing pre-created human WebAuthn private keys is not an accepted automation
mechanism.

No Terraform/Helm/CI path may call a different SQL owner-creation procedure that
bypasses the canonical semantics.

## 8. Canonical HTTP design

Exact spelling is CONTROLLED, but the first implementation should converge near:

### Setup discovery

```http
GET /v1/setup
```

Anonymous response contains only minimal state needed by a client:

```json
{"setup_required": true}
```

Do not leak owner email/count/IDs or security configuration.

### Create setup session

```http
POST /v1/setup/sessions
Idempotency-Key: ...
[optional deployment setup proof]
```

Response returns the raw SetupSession bearer once and expiry.

This operation MUST be rate-limited.

### Enrollment operations

Prefer session-relative semantic/resource endpoints, e.g.:

```text
POST /v1/setup/native-identity
POST /v1/setup/webauthn/registration-options
POST /v1/setup/webauthn/registrations
POST /v1/setup/recovery-codes
POST /v1/setup:finalize
```

Exact REST shape must be checked against docs 15/16 during implementation.

Do not expose a generic setup command bus.

### Finalize

```http
POST /v1/setup:finalize
Idempotency-Key: ...
Authorization: Setup <opaque-token>
```

Semantic result returns owner/instance identifiers and normal next-step metadata,
not raw recovery codes.

Replay with the same idempotency identity returns the same non-secret semantic
result. Same key with a different request fingerprint fails closed.

A retry must never redisplay one-time recovery codes.

### Post-claim behavior

After claim:

- `GET /v1/setup` may report `setup_required=false`;
- session creation/finalize endpoints return a stable closed/conflict result;
- no hidden query parameter/header reopens them.

## 9. Atomic finalize transaction

The final authoritative command should follow:

```text
READ
  load setup/session/enrollment facts

PLAN
  resolve platform-owner-v1 immutable policy

LOCK
  identity-topology gate according to accepted lock ordering
  platform Instance row / platform Principal serialization root
  needed identity/authenticator rows

VALIDATE
  instance unclaimed
  setup usable
  authentication posture sufficient
  native authority active
  policy exists
  no conflicting terminal state

WRITE
  create/activate Platform Principal
  create active platform identity binding
  grant exact policy capabilities
  append installation-claim audit/provenance
  mark setup consumed
  mark Instance CLAIMED + initial owner

EMIT
  durable non-secret audit/outbox/security event if required
```

No external network I/O while locks are held.

If another finalize wins first, the loser performs **zero platform-authority
writes** and receives deterministic conflict semantics.

## 10. Platform Owner policy

Introduce immutable `platform-owner-v1`.

Do not blindly copy every registered capability. Define the intentional owner
ceiling.

Expected families include enough authority to:

- provision organizations;
- create/invite/manage additional platform controllers/admins;
- inspect/manage platform identity/recovery;
- manage platform configuration;
- manage secret references/rotation operations when those APIs exist;
- inspect platform audit/readiness.

Capabilities that do not yet have a real operation SHOULD NOT be added merely to
make the policy look complete.

`platform.principal.grant/revoke` (or semantically better owner operations) is
still a missing product surface and should be designed explicitly before multiple
owner/admin lifecycle is considered complete.

Owner label != wildcard.

## 11. Authentication assurance model

Current `authenticated_at` is insufficient for MFA/passkeys.

Extend trusted authentication evidence so PlatformActorContext can reason about:

```text
authenticated_at
authentication_methods
authentication_assurance
user_verification
credential/authenticator identifiers where needed
recovery-derived session flag where needed
```

Recommended assurance classes:

```text
SINGLE_FACTOR
MFA
PHISHING_RESISTANT
RECOVERY
```

Names may change; semantics must not.

Examples:

- password only -> SINGLE_FACTOR;
- password + TOTP -> MFA;
- verified WebAuthn with required UV -> PHISHING_RESISTANT;
- recovery-code restoration -> RECOVERY until a normal strong factor is
  re-established.

Do not infer assurance from the presence of a credential record; derive it from
the authentication ceremony that produced/refreshed the session.

## 12. Step-up policy

Replace one-dimensional "fresh enough" reasoning with:

```text
required capability
+
operation risk
+
authentication freshness
+
authentication assurance
```

Suggested baseline:

- ordinary read: valid session;
- low-impact write: valid session;
- sensitive configuration: MFA/recent auth as owner contract requires;
- secrets, MFA-factor changes, owner grants/revokes, native identity disable:
  recent PHISHING_RESISTANT HUMAN authentication;
- recovery-derived sessions cannot immediately perform high-risk authority change
  until a normal phishing-resistant authenticator is enrolled/proved.

Retain the accepted five-minute recent-authentication default for high-risk
operations unless a newer ADR changes it.

Do not hard-code these checks independently in routers. Drive them through
central operation/capability policy or a narrow reusable enforcement mechanism
without creating a second capability registry.

## 13. Password modernization

Current native password verifier uses scrypt at parameters below current OWASP
recommendations. The trust-root work should not cement that as the new platform
admin baseline.

Recommended implementation:

- introduce versioned Argon2id verifier support;
- continue verifying existing scrypt hashes;
- on successful legacy-password authentication, opportunistically rehash with
  current Argon2id parameters;
- never downgrade a stronger/current verifier;
- password remains optional in the future architecture, but initial migration may
  keep password + passkey for simplicity.

Do not force a mass reset merely to change verifier algorithm.

Exact Argon2id parameters must be benchmarked in the target runtime while meeting
current OWASP guidance; do not cargo-cult one cost value without memory/CPU
evidence.

## 14. Platform login/session policy

For platform control:

- session TTL may remain near the existing 12-hour overall bound initially;
- enable bounded idle timeout (proposal 30-60 minutes; choose via measured UX);
- rotate/invalidate sessions after credential/factor compromise events;
- normal logout and logout-all remain available;
- passkey authentication can create a normal native session with explicit
  assurance evidence;
- sensitive actions require fresh step-up rather than forcing full login for every
  request.

Do not let bearer/API tokens inherit human step-up capability merely because the
issuing human was an Owner.

## 15. Control-plane registration surface

The current control plane mounts the general native auth router including
anonymous native identity enrollment.

Target behavior:

```text
UNCLAIMED
  -> setup-specific enrollment only

CLAIMED
  -> no anonymous platform-user enrollment
  -> new platform humans arrive through invitations/governed provisioning
```

Tenant/public identity enrollment decisions remain separate and must not be
silently changed by the platform setup work.

Do not reuse an anonymous platform enrollment endpoint as the invitation system.

## 16. Additional Platform Owners/Admins

After first claim:

```text
existing authorized HUMAN
  -> create invitation / desired platform membership
  -> one-time invitation proof
  -> invitee establishes/proves identity
  -> required MFA/passkey enrollment
  -> authority granted within delegable ceiling
  -> invitation consumed
```

Required protections:

- no password chosen by the inviter;
- no authority by email-domain inference;
- stable idempotency;
- revision checks;
- no self-elevation;
- actor may grant only authority explicitly delegable by policy;
- post-state must retain an effective controller;
- owner/admin changes are append-audited;
- high-risk owner grant/revoke requires recent phishing-resistant HUMAN auth.

A future dual-control requirement for the highest-risk owner changes remains a
valid extension. Do not fake dual control when only one human exists.

## 17. Recovery architecture

Three different recovery problems must remain distinct:

### 17.1 Normal account recovery

Current governed identity-recovery case machinery.

### 17.2 MFA/factor recovery

A logged-out user with valid recovery codes or approved recovery may regain
limited identity access and re-enroll factors.

### 17.3 Instance break-glass recovery

Used only when no normal effective Platform Owner can authenticate.

Rules:

- never set Instance back to UNCLAIMED;
- never reopen setup;
- deployment proof is separate from user credentials;
- prefer restoring an existing owner;
- emergency replacement authority, if ever supported, requires an explicit
  accepted contract;
- every ceremony leaves immutable provenance;
- no universal `force=true`;
- no raw recovery proof in ordinary audit/log/outbox.

The existing ADR 0013 double-control recovery semantics remain authoritative
where applicable.

## 18. Configuration and secret administration after trust root

Do not block initial claim on SMTP, Vault-backed provider secrets or external IdP.

After claim, design separate APIs for:

```text
non-secret platform configuration
secret metadata/write/rotate
delivery/provider configuration
readiness/test operations
```

Normal settings may be versioned in PostgreSQL.

Raw provider secrets should pass through a SecretStore abstraction and the DB
stores references/metadata, not replayable plaintext.

There will always remain minimal deployment-root configuration needed before the
app can read runtime-managed secrets, e.g. DB connectivity and secret-store
authentication. The goal is not "zero environment settings"; the goal is the
smallest possible deployment trust root.

## 19. Security notifications and audit

Security-significant events include at least:

- Instance claim finalized;
- setup claim conflict/race attempts (rate-limited/aggregated, avoid log DoS);
- WebAuthn/TOTP factor added/revoked;
- recovery-code set regenerated / code used;
- password changed;
- platform owner/admin invited/granted/revoked;
- identity disabled;
- instance recovery initiated/completed;
- external IdP/platform auth policy changed.

Audit records contain identifiers/provenance, never raw tokens, passwords, TOTP
seeds, recovery codes, WebAuthn challenges or provider secrets.

SMTP notification delivery is useful after configuration but is not the
authoritative audit channel.

## 20. Rate limiting and abuse controls

Unauthenticated setup exists only while unclaimed, but still requires abuse
controls:

- rate-limit SetupSession creation by deployment/network-safe signals;
- cap active setup sessions;
- strict body limits;
- cheap structural validation before expensive password hashing/WebAuthn work;
- timeouts;
- generic errors that do not expose unnecessary state;
- no expensive total-count/database scans in setup discovery.

Do not use global account lockout as the primary setup DoS defense.

## 21. Network, browser and deployment boundary

The setup API lives in the **control-plane process**, never the tenant/data-plane
app.

Reference deployment should support:

```text
public/data API       -> business/public ingress
platform control API  -> administrative ingress
PostgreSQL/Vault      -> backend only
```

Production deployments should be able to add network restrictions, VPN,
Cloudflare Access, mTLS or private ingress without changing Request Engine's
authorization semantics.

Network hiding is defense in depth, not the claim invariant.

### 21.1 TLS, Origin and browser protections

Production setup, WebAuthn and authenticated control-plane traffic require HTTPS.
Development exceptions must be explicit and limited to local origins allowed by
the WebAuthn/browser model.

CORS must be an allowlist, never reflective wildcard behavior for administrative
credentials. WebAuthn registration/authentication validates the exact expected
origin and RP ID from trusted configuration, not request headers supplied by the
client.

If the future admin UI uses cookies, use Secure + HttpOnly + appropriate SameSite
semantics and explicit CSRF protection for state-changing requests. If it uses
bearer tokens, do not place long-lived administrative tokens in localStorage by
default. The UI transport decision must not weaken the API's server-side
authorization checks.

SetupSession bearer material should be sent in an authorization header rather
than ambient browser cookies unless an explicit CSRF-safe cookie design is
accepted.

Apply security headers appropriate to the admin UI (at minimum a restrictive CSP,
frame-ancestor protection and no-sniff behavior) when that UI exists.

### 21.2 WebAuthn RP ID is operational identity

RP ID is not a cosmetic setting. Existing WebAuthn credentials are scoped to it.

Therefore:

- derive RP ID from explicit trusted configuration, not arbitrary Host headers;
- validate configured origins against the intended administrative URL;
- changing the administrative domain/RP ID is a credential migration event, not
  an ordinary runtime toggle;
- readiness should fail closed for an invalid RP/origin combination;
- document disaster-recovery DNS expectations so restoring the same Instance can
  continue using existing authenticators when intended.

Do not silently rewrite RP ID after deployment because a reverse proxy hostname
changed.

## 22. Idempotency and ambiguous client outcomes

Every setup mutation that may be retried after connection loss needs explicit
semantics.

Particularly finalize:

```text
same Idempotency-Key + same fingerprint
  -> same non-secret semantic result

same key + different fingerprint
  -> conflict

different key after another claim won
  -> instance already claimed
```

One-time secrets are excluded from replay responses.

Client disconnect after DB commit must not make the client create a second owner.

## 23. Concurrency proofs

At minimum prove with independent DB transactions/connections:

1. two SetupSessions finalize concurrently -> exactly one owner/claim wins;
2. losing transaction leaves no grants/binding/platform Principal side effects;
3. setup finalization racing native-authority disable -> one valid serialized
   outcome, never an owner bound to unusable authority;
4. claim racing platform topology/global identity mutation follows D5 lock order;
5. replay after successful claim is idempotent;
6. old CLI/SQL bootstrap path cannot create a second platform root after new claim;
7. process restart during unfinished SetupSession does not create authority;
8. restore/restart of claimed database never reopens setup.

Timing-only sleeps are not sufficient evidence.

## 24. E2E acceptance suite

Add a dedicated system/E2E suite through the existing reusable suite registry,
not a new Compose architecture.

Black-box runner must have:

- HTTP/TCP access to control plane and required provider doubles;
- no PostgreSQL credentials;
- no Request Engine application imports;
- no bootstrap CLI;
- no Docker socket unless outer fault-injection orchestrator owns it.

Minimum journey:

```text
fresh world
-> GET setup_required=true
-> create SetupSession
-> establish identity
-> register software WebAuthn authenticator through real ceremony
-> create/acknowledge recovery codes
-> finalize owner
-> setup_required=false
-> normal passkey/password login
-> call authorized platform operation
-> anonymous second claim rejected
-> tenant admin cannot call platform operation
-> restart control plane/API/Postgres as supported
-> setup remains closed
```

Adversarial checkpoints:

- wrong/expired setup token;
- expired SetupSession;
- reused challenge;
- wrong origin/RP ID;
- invalid WebAuthn signature;
- missing user verification;
- concurrent finalize;
- reused recovery code;
- high-risk command with stale auth;
- high-risk command with TOTP-only/recovery assurance when phishing-resistant
  step-up is required;
- delete/revoke attempt against last effective controller;
- emergency recovery does not reopen setup.

The WebAuthn test authenticator must produce real cryptographic assertions. Do not
mock `verified=true`.

## 25. Unit/module/PostgreSQL evidence

Do not rely only on E2E.

Required proof layers:

### Pure/unit

- state transition policy;
- assurance classification;
- idempotency fingerprinting;
- password verifier version selection;
- recovery-code formatting/digest verification;
- WebAuthn option policy composition.

### PostgreSQL 18

- singleton Instance invariant;
- one-way claim transition;
- policy/grant exactness;
- lock ordering and concurrent winner/loser;
- append-only provenance;
- last-controller continuity;
- direct table privilege denial for runtime logins.

### HTTP/module

- OpenAPI contracts;
- error/status semantics;
- cache-control on secrets/setup;
- auth boundary separation;
- setup router not mounted on data plane;
- post-claim closed behavior.

### System/E2E

- real processes/TCP/crypto as section 24.

## 26. Database-role/least-privilege implications

Do not give the control-plane HTTP login direct table superpowers just because
setup is unauthenticated.

The canonical setup command should execute through a narrow audited DB surface
with only the columns/functions it needs.

Startup verification in `platform_server.py` must be updated so:

- the control-plane write login has exactly the new required command surfaces;
- obsolete bootstrap-only privileges are not accidentally inherited;
- app/public auth login still has no platform-authority function access;
- no runtime login is superuser/BYPASSRLS/CREATEROLE/CREATEDB.

Schema-owner/bootstrap migration credentials remain deployment-only and never
become front-end credentials.

## 27. Migration strategy from current bootstrap

Existing migration history is immutable.

Implementation sequence:

1. append Instance/setup/authenticator/policy migrations after current head;
2. introduce HTTP setup surface behind the new data model;
3. make Docker clean-install E2E use HTTP setup;
4. remove runtime dependency on `platform_bootstrap_cli.py`;
5. remove CLI from the reference installation path and docs;
6. audit references to `platform_bootstrap_intents` and old bootstrap role/function;
7. append a later migration to revoke/drop obsolete runtime surfaces/tables if no
   current guarantee/provenance requires retaining them;
8. never edit 0011/0012 in place.

Because Request Engine is pre-production, compatibility with an externally
supported bootstrap CLI is not a product requirement, but migration history and
schema upgrade correctness still are.

## 28. Existing policy inconsistencies to close during implementation

Do not let this work hide known debt:

### Tenant initial policy

Current Python still defaults new native organizations to
`tenant-controller-v3` while immutable v4/v5 exist. Determine the intentional
current policy and update provisioning/tests coherently. Do not blindly replace
the string without checking what capabilities v4/v5 imply.

### Root capability drift

Current migrations added capabilities to existing platform controllers in later
revisions while new-root establishment historically had an older grant list.
The new `platform-owner-v1` catalog eliminates this drift by giving initial
claim one explicit policy source.

### Open control-plane enrollment

Replace anonymous generic enrollment on the claimed platform plane with
invitation/governed flows.

### Password verifier

Modernize without invalidating current valid users.

## 29. Implementation slices

### P0 — Contract reconciliation

- inventory current HEAD, branch/lane and exact migrations;
- enumerate every caller/reference of bootstrap CLI/intents/root establishment;
- enumerate platform controller predicate inputs;
- record current auth/session DB roles and ACLs;
- confirm exact current E2E topology;
- reconcile docs/guarantees before behavior changes.

### P1 — Instance + setup-session persistence

Deliver:

- Instance singleton;
- setup sessions;
- one-way state guards;
- narrow readers/commands;
- PostgreSQL concurrency tests;
- no owner creation yet.

### P2 — WebAuthn + assurance primitives

Deliver:

- registration/authentication challenge lifecycle;
- credential storage;
- real verification;
- assurance evidence;
- session propagation;
- factor lifecycle basics;
- test software authenticator.

Do not yet weaken existing password login.

### P3 — Recovery codes + password modernization

Deliver:

- digest-only recovery code sets;
- safe one-time presentation contract;
- Argon2id versioned password verifier;
- legacy scrypt verification + opportunistic rehash.

### P4 — Atomic HTTP Instance claim

Deliver:

- setup HTTP operations;
- finalize command;
- platform-owner-v1;
- exact DB transaction/locks;
- setup permanently closes;
- system/E2E clean install no longer calls bootstrap CLI.

This is the point where ADR 0014 becomes executable product behavior.

### P5 — Platform owner/admin lifecycle

Deliver:

- invitation/provisioning;
- explicit platform grant/revoke semantics;
- self-elevation prevention;
- last-controller continuity;
- recent phishing-resistant step-up for authority changes;
- second-controller positive E2E path.

### P6 — Instance recovery

Deliver:

- deployment recovery trust adapter;
- normal-vs-instance recovery separation;
- break-glass drill;
- no setup reopening;
- audit/security notification behavior.

### P7 — Configuration/secrets admin APIs

Only after trust root is stable:

- SMTP/provider configuration;
- secret references/write/rotation;
- runtime validation/readiness;
- no secret replay;
- admin UI can later consume these operations.

## 30. Failure semantics

Stable machine-readable errors should distinguish at least:

```text
setup_closed
setup_protection_required
setup_protection_invalid
setup_session_invalid
setup_session_expired
setup_step_incomplete
webauthn_challenge_invalid
webauthn_verification_failed
phishing_resistant_auth_required
recent_authentication_required
platform_authority_changed
platform_controller_continuity_violation
idempotency_conflict
```

Exact HTTP status follows docs 15 and current error-envelope conventions.

Security-sensitive failures should not expose whether unrelated identity material
exists.

## 31. Observability

Metrics/logs/traces should answer:

- Is instance claimed?
- How many setup sessions are being attempted/rate-limited?
- Are WebAuthn verification failures rising?
- Are platform login failures rising?
- Are high-risk step-up failures occurring?
- Does the platform still have >=1 effective controller?
- Is break-glass recovery being invoked?
- Are secret/delivery dependencies healthy?

Never include raw authentication material in telemetry.

A security event and an operational metric are different artifacts; do not use
logs as the only audit store.

## 32. Backup/restore and cloning

Restore requirements:

- claimed backup restores as claimed;
- SetupSession secrets from an old backup should be expired/rejected by TTL and
  cannot create a second claim;
- Instance ID is preserved on true disaster recovery;
- WebAuthn credentials remain usable only if the restored deployment preserves a
  compatible RP ID/origin; restore tooling must not pretend otherwise;
- recovery-code used/unused state is authoritative data and must restore
  consistently with the identity database.

Cloning production DB to staging creates an identity problem: two deployments
would share Instance ID, owner/authenticator material and potentially valid
recovery/session state.

Before production acceptance, define a restore/clone fencing procedure that can:

- identify intentional disaster recovery vs environment clone;
- prevent a staging clone from sending production SMTP/webhooks;
- rotate/rebind environment-specific secrets;
- deliberately mint a new Instance identity only through an explicit clone
  operation, never automatically on container startup.

Do not solve this by "if hostname changed, reset instance".

## 33. Security posture/readiness projection

A future read-only platform readiness endpoint may compose facts such as:

```text
owner_phishing_resistant_auth: ready
recovery_codes: ready
second_platform_controller: recommended
smtp: configured/unconfigured
secret_store: ready/unavailable
external_idp: optional/configured
backup_restore_drill: unknown/ready
```

This is a diagnostic projection, not an authorization source and not a gamified
security score.

Onboarding/readiness composition must not become owner of these underlying facts.

## 34. Documentation updates required with implementation

When behavior begins changing, update coherently:

- `docs/README.md`;
- `architecture/auth-production-completion-plan.md`;
- `architecture/auth-implementation-status.md`;
- `architecture/docker-e2e-ci-plan.md`;
- current guarantee inventory/proof map;
- API/OpenAPI documentation;
- migration README if schema/runtime topology changes;
- recovery documentation;
- reference deployment README.

Do not leave historical "bootstrap CLI is canonical" statements in current
authority after P4.

## 35. Definition of Done

The trust-root project is complete only when all are true:

### Product

- fresh self-hosted install can claim owner without CLI/SQL;
- first owner cannot become effective without verified phishing-resistant
  authenticator;
- setup closes permanently;
- second platform controller can be invited and activated;
- last effective controller cannot be removed;
- owner recovery does not reopen setup.

### Security

- no superuser bypass;
- no raw setup/password/TOTP/recovery secret stored in ordinary DB/log/audit;
- high-risk authority changes require recent phishing-resistant HUMAN proof;
- password verifier is modern/versioned;
- runtime DB roles remain least privilege;
- origin/RP/challenge/WebAuthn verification is real.

### Concurrency

- exactly one first claim wins under deterministic race proof;
- losing/replayed claims have no duplicate authority side effects;
- lock ordering conforms to D5.

### HTTP/TCP evidence

- clean-install journey starts from fresh DB and uses only network-facing
  supported interfaces;
- E2E runner has no DB/app-internal shortcut;
- real software WebAuthn assertion is verified;
- restart/restore checks prove setup remains closed.

### Operations

- reference deployment documents interactive/protected/automated setup;
- break-glass recovery is documented and drilled;
- security/audit telemetry is useful without leaking secrets.

### Documentation

- current docs contain one non-contradictory canonical trust-root story;
- old CLI material is historical/transition-only, not current authority.

## 36. Explicit stop line

Do not continue adding bootstrap/security mechanisms indefinitely.

For this project, the necessary trust-root scope ends when P1-P6 and the above
Definition of Done are satisfied.

Admin UI, billing automation, generalized configuration management, extra IdPs,
adaptive risk scoring and hardware-attestation policy are follow-on projects
unless implementation reveals a concrete blocker.

The objective is a small, comprehensible, testable trust root — not an IAM
product hidden inside Request Engine.
