# Platform configuration, OpenBao and access-recovery implementation plan

Date: 2026-09-19  
Branch: `feature/platform-config-openbao-recovery`  
Authority: ADR 0015

> **P7 execution handoff (2026-09-20):**
> `p7-platform-configuration-secrets-implementation-handoff.md` is the
> executable continuation for the deferred P7 surface. This document remains the
> requirements/Definition-of-Done source; the handoff reconciles those
> requirements with the delivered P1-P6 trust root and current worker/secret
> architecture.

## 1. Objective

Move Request Engine toward a self-hosted control plane where operational
configuration can change without redeploying the application, reversible secrets
are stored outside ordinary business tables, and loss/outage of that secret
manager does not lock the Platform Owner out.

Target architecture:

```text
minimal deployment bootstrap
          |
          v
   Request Engine control plane
      |                 |
      | non-secret      | secret lifecycle
      v                 v
 PostgreSQL       PlatformSecretStore
                        |
                        v
                 OpenBao (reference)

Offline Platform Owner recovery codes
          |
          +----> native password reset
                 (independent of OpenBao/SMTP)
```

## 2. Delivered in this branch

### 2.1 Offline access recovery

Migration `0068_offline_password_reset` introduces the atomic
`request_auth.consume_recovery_code_and_rotate_password` primitive.

The control plane exposes:

```text
POST /auth/native/password:recover-with-code
```

Input contains only:

- one recovery code;
- a new password.

It does not accept an identity selector. The code determines the identity.

One successful transaction:

1. locks and consumes the one-time code;
2. verifies the native authority and identity remain active;
3. replaces the active password credential;
4. bumps the native identity session epoch;
5. revokes existing native sessions;
6. revokes pending delivery-based recovery intents;
7. appends recovery provenance.

The previous password is not recoverable and is never returned.

### 2.2 Provider-neutral secret boundary

`PlatformSecretStore` defines:

- create/rotate with expected version;
- trusted runtime resolve;
- metadata without plaintext;
- revoke.

Callers use opaque UUID secret IDs, never backend paths.

### 2.3 OpenBao reference implementation

`OpenBaoPlatformSecretStore` uses KV v2 and CAS.

`OpenBaoRecoverySecretStore` implements the existing temporary recovery-proof
store so OpenBao can replace Vault as the self-hosted reference backend without
conflating temporary proof staging with the general platform secret store.

`RecoveryDeliverySettings` accepts OpenBao configuration. Configuring OpenBao
and Vault simultaneously fails closed.

### 2.4 Self-hosted deployment reference

`deploy/openbao/` contains:

- OpenBao 2.6 Raft server config;
- OpenBao Proxy + AppRole auto-auth config;
- separate runtime/control policies;
- Docker Compose reference;
- initialization/recovery documentation.

The reusable Docker E2E `secrets` profile now uses OpenBao dev mode instead of
HashiCorp Vault dev mode.

### 2.5 Private configuration core (0069)

Migration `0069_platform_configuration` establishes the private persistence
foundation without prematurely granting application mutation authority:

- typed `configuration_kind` / `provider_kind` revisions;
- immutable staged payload and secret-binding identity;
- monotonic draft -> validated -> active -> superseded/disabled lifecycle;
- at most one ACTIVE revision per configuration kind;
- opaque secret bindings storing backend/id/version metadata only;
- append-only configuration facts;
- no direct `request_engine_app` CRUD on these private global tables.

The governed command/API surface was delivered in the P7-B/P7-C slices (see
section 3).

## 3. Slice status (checkpoint 2026-09-23, HEAD `79b257fa`)

This section originally listed surfaces that were not yet built. Slice-level
status is now tracked in
`p7-platform-configuration-secrets-implementation-handoff.md` section 0/2. In
summary:

- control-plane configuration CRUD/stage/validate/activate APIs — implemented;
- secret admin APIs — implemented;
- SMTP candidate validation/test/activation — implemented; TLS/AUTH protocol
  conformance proven against a real SMTP server (certificate-verifying SMTPS and
  STARTTLS, `INV-SMTP-TRANSPORT-SECURITY-001`); production SMTP acceptance
  outstanding;
- runtime configuration cache + invalidation/hot reload — implemented; the
  `platform-configuration` black-box journey now runs without any
  `REQUEST_ENGINE_SMTP_*` bootstrap configuration, proves managed delivery and
  hot reload, and the real-PostgreSQL polling convergence proof passes in CI;
- notification intents/templates — managed webhook path implemented; generic
  Communications email rendering still absent by design;
- product readiness projection — implemented for durable SMTP plus deployment clone-fence, secret-store, recovery-delivery and optional-OIDC facts; backup/restore evidence remains unknown until P7-K;
- signing-key keyrings/rotation — pending;
- OIDC provider administration — pending;
- automatic backup scheduling — pending;
- clone fencing implementation — implemented and black-box proven; backup/snapshot/restore drill remains pending.

Mutations require governed Platform Owner authority plus recent phishing-resistant
authentication as required by the P7-DoD and handoff.

## 4. Required P7 lifecycle

Configuration is typed, not generic KV.

```text
DRAFT -> VALIDATED -> ACTIVE -> SUPERSEDED
            \-> DISABLED
```

Validation is an operation in the current synchronous provider model, not a
separate durable VALIDATING state. If a future provider requires asynchronous
validation, that state must be introduced together with its worker semantics and
failure/retry contract.

There may be many candidate revisions but at most one ACTIVE revision per
configuration kind.

Activation must be serialized in PostgreSQL.

## 5. Secret lifecycle

PostgreSQL stores only metadata/reference facts:

```text
binding id
purpose
backend
opaque secret id
backend version
state
created/rotated/revoked timestamps
actor/provenance
```

Plaintext lives only in OpenBao and transient runtime memory.

Administrative reads return:

```text
configured: true
version: 4
last_rotated_at: ...
```

never the original value.

## 6. Runtime reload

Future provider resolvers consume the active PostgreSQL revision and use
revision-keyed in-memory caches.

Activation emits a PostgreSQL notification to invalidate caches; periodic
revision checks reconcile missed notifications.

PostgreSQL remains authoritative. LISTEN/NOTIFY is an optimization, not truth.

## 7. SMTP first provider

SMTP is the first configuration consumer because it is protocol-based and fully
self-hostable.

The target flow is:

```text
stage config
 -> write credential to PlatformSecretStore
 -> validate TCP/TLS/AUTH
 -> optional test mail
 -> activate
 -> workers observe new revision without restart
```

IMAP is not required for outbound notification delivery.

## 8. Notification boundary

Business modules produce a `NotificationIntent`; they do not invoke SMTP
directly.

```text
domain transaction
 -> durable notification/outbox intent
 -> worker
 -> configured channel/provider
```

SMTP ambiguous post-transmission outcomes stay UNKNOWN and are not blindly
republished.

## 9. Authentication and authorization

Future secret/config mutation capabilities must be explicit, e.g.:

```text
platform.configuration.read
platform.configuration.stage
platform.configuration.validate
platform.configuration.activate
platform.configuration.disable
platform.secret.write
platform.secret.rotate
platform.secret.revoke
platform.provider.test
```

There is intentionally no human `platform.secret.read_plaintext` capability.

High-risk mutation requires the existing recent
`PHISHING_RESISTANT` authentication guard.

## 10. Recovery hierarchy

Normal access:

```text
passkey -> PHISHING_RESISTANT session
password -> SINGLE_FACTOR session
```

Account-level emergency:

```text
offline Request Engine recovery code
 -> replace password
 -> revoke old sessions
 -> login with new password
 -> perform WebAuthn registration/repair through governed flow
```

This path is independent of OpenBao.

Secret-store disaster:

```text
OpenBao unseal/recovery shares
 + Raft snapshot
 -> restore OpenBao
 -> recreate AppRole/Proxy machine credential
 -> rebind runtime
```

Full-host disaster:

```text
PostgreSQL backup
 + OpenBao snapshot
 + OpenBao unseal material
 + Request Engine offline recovery codes
 + deployment/TLS material
 -> rebuild
```

## 11. Definition of Done

The overall program is done only when all of the following are demonstrated.

### Access recovery

- fresh Instance Claim presents offline recovery codes exactly once;
- only digests are durable;
- an unused code can reset the Platform Owner password with SMTP and OpenBao
  completely unavailable;
- reset is atomic with code consumption;
- old password stops working;
- old sessions stop working;
- new password works;
- same recovery code cannot be reused;
- setup remains permanently closed;
- no API reveals the old password or stored recovery code.

### Secret storage

- no mandatory SaaS;
- OpenBao is runnable on self-hosted infrastructure;
- Request Engine depends on `PlatformSecretStore`, not OpenBao business
  semantics;
- admin APIs never replay plaintext;
- secret rotation is CAS/version protected;
- AppRole/Proxy removes static long-lived token requirements from Request Engine;
- least-privilege runtime/control policies are separate.

### Configuration plane

- typed revision persistence exists;
- exactly one ACTIVE revision per kind;
- validation precedes activation;
- stale concurrent activation fails;
- SMTP can be configured/tested/activated from control plane;
- active SMTP changes take effect without Request Engine restart;
- recovery delivery no longer requires SMTP credentials in process environment;
- OIDC/provider credentials use secret references rather than ordinary columns;
- configuration and secret mutations are auditable.

### Disaster recovery

- automated PostgreSQL backups exist;
- OpenBao Raft snapshots exist;
- backup copies are encrypted/off-host;
- restore drill is documented and exercised;
- clone-to-staging fences outbound providers;
- losing OpenBao alone does not prevent Platform Owner account recovery;
- losing SMTP alone does not prevent Platform Owner account recovery;
- losing a passkey alone does not prevent Platform Owner account recovery when an
  offline recovery code remains;
- impossible-loss cases are documented honestly; no hidden master backdoor exists.

### CI evidence

- DB invariant/adversarial/concurrency tests execute in current-product gate;
- HTTP E2E proves first-owner offline recovery;
- OpenBao adapter contract tests execute;
- Docker E2E exercises the OpenBao secrets profile;
- guarantee/proof-map validation has no execution gaps;
- exact-head CI and Docker E2E are green.

## 12. Stop conditions

Do not mark the whole P7 program complete merely because OpenBao is installed.

Do not implement configuration mutation APIs before their Platform Owner
authority policy and recent phishing-resistant guard are established.

Do not make OpenBao availability a prerequisite for the offline account recovery
endpoint.

Do not add a universal master password or direct SQL operator reset as a product
recovery feature.
