# Platform administration: safe reads and native provisioning

Tenancy owns these platform-scoped operations. Organization creation does not
create an account, and account creation does not grant tenant membership or
authority. Staff membership/authority operations remain the tenant-owned journey.

## Operation gate

| Operation | HTTP | Capability | Policy |
| --- | --- | --- | --- |
| `platform_owner_list/get` | GET `/v1/platform/owners[/{principal_id}]` | `platform.owner.read` | Current HUMAN authority, no mutation |
| `platform_owner_invitation_list/get` | GET `/v1/platform/owner-invitations[/{invitation_id}]` | `platform.owner.read` | Current HUMAN authority, no secret disclosure |
| `platform_native_identity_provision` | POST `/v1/platform/native-identities` | `platform.identity.provision` | Native HUMAN actor; required `Idempotency-Key`; current authority before receipt |

These are typed owner Queries/Commands and resource HTTP projections. They do
not need a second agent execution path. Their current operation metadata remains
the shared source for admin/tool discoverability; visibility never grants access.

Owner reads project principal state, current authority revision, binding status
and capabilities. Invitation reads project lifecycle revision/timestamps and
expiration, never tokens, secret fingerprints, password material or recovery
proofs. `expired` is a time observation, not permission to activate an invitation.
Reads revalidate the trusted principal revision and active capability in the DB.

## Input and pagination

Platform collection filters are closed. Unsupported organization selectors or
invented filters return 422 rather than silently changing nothing. `after` and
`limit` are keyset pagination, with limits 1–100. Native identity, organization
and provisioner readers obtain one internal lookahead row in the same SQL
statement/snapshot without widening existing read-function limits. The HTTP
projection returns at most the requested limit; `next_after` exists only when a
real additional row was observed. Concurrent changes between pages remain normal
keyset behavior, not a snapshot transaction spanning requests.

Native identity reads/writes and owner reads publish native bearer security and
successful responses carry `Cache-Control: no-store`.

## Provision command protocol

READ/PLAN: validate a typed input, normalize the login handle and strip surrounding
idempotency-key whitespace. Stripping defines deliberate equivalence of header
keys; it is not applied to password bytes. The password is excluded from command
repr and durable receipt storage. An operation/authority/actor/key-scoped salt
and pinned Argon2id intent-v1 profile produce costly deterministic password
material, hashed together with normalized login and authority. Future login
password-cost upgrades must not change this receipt profile. Login verification
uses a separate random salt. Both expensive computations happen outside locks.

LOCK: one explicit platform actor transaction acquires topology SHARE, the actor
principal UPDATE root, native authority SHARE, identity SHARE, credential SHARE
and native session SHARE, in that order.
Topology mutations/global disable take EXCLUSIVE, and password rotation/recovery
uses authority-before-identity-before-credential ordering. The narrow technical
helper holds authentication posture locks without publishing native secrets.

VALIDATE: current active HUMAN platform principal, exact authority revision,
active provision capability, native-session provenance, active binding matching
both identity and native authority, accepted password/passkey credential, active
native identity/authority and no recovery restriction. Validation precedes every
receipt read. A saved answer cannot restore withdrawn authority.
Trusted `credential_id` retains its existing native-session UUID meaning in
actor/audit context. Migration 0022 resolves that session's immutable password
or WebAuthn provenance, then checks current session status, expiration, identity
epoch and non-recovery authentication before replay. A direct authenticator UUID
is not an accepted session or an alternate execution path. Token-secret proof
and configured idle timeout remain ingress responsibilities.

WRITE: one native identity and login credential plus one immutable actor/key
receipt in the same transaction. Actor serialization gives concurrent identical
retries one result. Conflicting key intent or duplicate login returns a sanitized
409; withdrawn actor posture returns 403; malformed policy/input returns 422;
unavailable native authority returns the owning availability failure. Provisioning
does not create a principal, binding, tenant membership or grants implicitly.

The receipt stores only actor/key digest, intent digest, created identity/login,
correlation and time. No runtime table DML is granted. The command runs through a
private platform definer with narrow grants; the technical authentication helper
is schema-owner SECURITY DEFINER with fixed search path and no PUBLIC/runtime
EXECUTE. It exposes only accepted identity UUID to the private command owner.

Receipt ACL evolution: migration `0023_native_receipt_columns` removes the broad
table SELECT/INSERT grants introduced by 0017. The primitive now projects exactly
actor, key digest, intent digest, native identity and login: those five columns
have SELECT. INSERT covers those five plus correlation. `created_at` is assigned
by its existing default, never by the definer; correlation/time cannot be read
through that owner, and UPDATE/DELETE remain forbidden. This strengthens
INV-PRIVILEGE-001 without changing receipt identity, ordering, RLS or replay truth.

The projection and ACL contraction commit atomically in one migration. The old
Python caller still invokes the same SQL signature and remains compatible. Do
not restore an old SQL function body containing `SELECT *` against these narrowed
ACLs: it cannot execute. Schema/function restoration requires a coordinated,
reviewed roll-forward repair, not silently regranting table privileges. No receipt
data is rewritten or lost; there is no production-sized data backfill. The small
DDL takes normal catalog/table grant locks, so apply it during a bounded migration
window with appropriate deployment lock timeout. A missing/ambiguous function
anchor aborts the transaction rather than producing a partly restricted command.
Drain the native-provision control lane before applying this contraction:
overlapping invocations may retain an old cached `SELECT *` body, and a zero-
downtime transition for those in-flight calls has not been proven. Resume only
after the migrated primitive and narrow-ACL replay checks pass.

Definer inventory disposition: four exact signatures introduced by 0014/0015
and owned by the private platform control definer after 0017 are approved in
the runtime schema gate. The three reads only inspect current platform
authority and secret-free owner/invitation metadata; they perform no writes.
The provision primitive needs its narrow receipt RLS policy and native-create
EXECUTE privilege, not tenant application authority. This is a CONTROLLED
inventory evolution, not blanket trust in that owner. Unknown control-definer
functions, PUBLIC execution and unsafe search paths still fail. The two technical
authentication helpers have separately checked schema-owner/private-definer
EXECUTE ACLs; application and platform-control runtime roles cannot invoke them
directly.

## Migration lineage and proof

0014 adds safe owner reads; 0015 adds provision receipts/primitive; 0016 repairs
required private execute and read-column ACL; 0017 assigns the primitive to its
platform RLS owner; 0019 adds native posture revalidation after 0018; 0022 corrects
that guard to consume actual native-session provenance after 0021. Applied
history and the accepted baseline are unchanged. 0023 restricts receipt column
ACLs and the installed projection. 0019 uses an explicitly checked
function-body anchor to preserve the previously installed primitive and ACL; a
missing anchor aborts migration rather than silently skipping the hardening.
It is roll-forward-only because removing the authority guard is not an ordinary
safe rollback.

Durable proof: `tests/db/test_native_identity_admin_provision.py` exercises real
PostgreSQL runtime roles, independent retry connections with observed lock wait
chains, conflict and withdrawal, real invitation creation followed by private
read, and native posture withdrawal before replay. Module HTTP tests reject
unsupported selectors before database access and prove exact-full final pages
do not invent continuation. These tests are registered in current-product CI.

Limitations: ingress still owns token-secret possession and configured idle timeout;
the primitive independently revalidates session expiration/logout and native posture.
Owner reads are metadata queries, not a substitute for activation readiness or
an email delivery journey. Browser acceptance, infrastructure/provider acceptance
and exact-head remote CI remain separate release evidence. Do not call production
ready based on the focused tests alone.
