# Native-first HTTP runtime

The supported ASGI composition factory is
`request_engine.bootstrap.server:create_app`. It composes native human sessions,
workload credentials, current Principal authority, agent delegation/policy and
the owner HTTP operations. OIDC is opt-in, not a prerequisite for native operation.

## Configuration

Supply configuration through the deployment's secret manager/environment; do not
commit a populated environment file. No development credentials are defaulted.

| Environment variable | Requirement |
| --- | --- |
| `REQUEST_ENGINE_DATABASE_URL` | Async SQLAlchemy PostgreSQL URL with a dedicated login inheriting `request_engine_app`; never the migration/bootstrap login |
| `REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID` | UUID of the active native authority established by bootstrap |
| `REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY` | Independently generated secret, at least 32 bytes |
| `REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY` | Independently generated secret, at least 32 bytes |
| `REQUEST_ENGINE_OIDC_ENABLED` | Defaults to `false`; enabling it reads current trusted authority configuration from PostgreSQL |
| `REQUEST_ENGINE_DATABASE_PROBE_TIMEOUT_SECONDS` | Positive timeout, defaults to 5 seconds, maximum 30 |

Apply the repository Alembic head with the separate migration credential before
starting HTTP. Bootstrap the platform trust root through
`request-engine-platform-bootstrap`; do not give its privileged DSN to HTTP.

```sh
uv run uvicorn request_engine.bootstrap.server:create_app --factory --host 127.0.0.1 --port 8000
```

For deployment, terminate TLS at a configured ingress, restrict trusted proxy
headers to that ingress and apply request-size, connection and authentication
rate limits there. Do not expose the development database to the internet.
Workers use their separate runtime entrypoint and database role.

Startup verifies the actual PostgreSQL login is an effective app-role member,
is not privileged and belongs to no other role. This also rejects non-inherited
memberships that could permit `SET ROLE`, including read-all-data and private
definer roles. An unavailable database or unsafe role prevents startup.
Startup also requires the configured authority to exist with `kind=native` and
`status=active`. A missing migration/read boundary fails startup; the runtime
does not create authorities, apply migrations or fall back to another provider.

`GET /health/live` reports process liveness. `GET /health/ready` performs a bounded
database query that checks the configured native authority and returns 503 without
database or authority details when unavailable. Disabling that authority after
startup makes the next probe unready. Liveness remains independent. These
are technical probes, not capability-bearing business operations, and are excluded
from OpenAPI. Readiness does **not** certify the complete migration head, tenant provisioning,
worker health, notification delivery or overall production acceptance.

`GET /openapi.json` describes the typed HTTP contract. Credentials and organization
context remain required at protected operations; discovery visibility never grants
authority. The runtime closes its database pool and owned OIDC HTTP client on
shutdown. Native-only composition creates no OIDC client.

The federated bearer arm accepts the implemented RFC 9068 access-token profile
(`typ=at+jwt`, RS256, API audience, issuer, subject, expiration, issued-at,
client ID and token ID). It does not accept a browser ID token as an API bearer.
This is not a hosted Google-login flow or a claim of compatibility with every
provider's token format. Authorities and explicit bindings must be configured
through a trusted administrative boundary; matching email never links accounts.
Live authority configuration is reread per authentication. JWKS keys are cached
for a bounded period, so providers must publish overlapping rotation keys before
using them. No external provider credentials are needed when this arm is disabled.

## Native credential input and rotation

Native enrollment, login and password rotation reject unknown input fields and
blank or oversized login handles at the transport boundary. Surrounding whitespace
and letter case are normalized consistently; a request cannot choose a different
identity authority by adding a body field. Validation errors never reflect passwords.

`PUT /auth/native/password` (`nativePasswordRotate`) remains an authentication
command, not a tenant capability or agent tool. The current password proves
authority over that native credential; a Principal or tenant is neither required
nor manufactured. A bad current password produces 401. After authenticating it,
a new password outside policy produces `422 password_policy_violation`, with
`no-store`, no credential mutation and no session revocation. Success rotates the
credential using the existing credential-ID concurrency guard and invalidates
old sessions. Responses never contain the submitted passwords.

There is no idempotency receipt for password rotation. Do not blindly retry an
ambiguous successful rotation with the old password: authenticate using the new
password to determine the outcome. Password hashing stays outside authoritative
database locks; the existing auth store retains transaction ownership. This
transport correction preserves the credential, revocation and no-implicit-authority
guarantees; it changes no password policy, DB credential protocol or provider trust.

## Acceptance boundary

This factory supplies deployment composition, not a certification that every
identity-plan requirement is complete. The required providerless onboarding,
staff lifecycle, explicit external binding administration, provider portability
and adversarial journeys remain defined in
`identity-provider-and-staff-provisioning-plan.md`, with slice ordering amended by
`principal-agent-and-provisioning-authority-model.md`.

Unit evidence checks fail-closed configuration, refused startup with an
unavailable database, and probe semantics; it is not PostgreSQL or public-network
E2E evidence.

## Opt-in platform authentication composition

`build_native_auth_runtime` can now receive a separate
`platform_session_factory`. Only that explicit composition exposes
`platform_actor_resolver`; it is `None` in the ordinary native-first API runtime.
The ordinary ASGI server intentionally does not expose platform provisioning.
An explicit private control-plane factory is available separately (below).

The subject authenticator remains provider-neutral and uses the app connection
for native session and exact identity-binding lookup. The separate connection
needs only schema USAGE and EXECUTE on
`request_platform.read_principal_authority(uuid)` for this read boundary; it must
not inherit app, worker, definer or bootstrap privileges. A future command
composition must separately name its authorized write connection. Never grant
platform-read/control privileges to `request_engine_app` to reuse its pool.

Composition, not request data, chooses the trust plane. Platform resolution rejects
`X-RE-Organization-ID`, including empty or malformed values. Principal, capabilities
and revision are resolved from RE facts, not supplied by caller headers. An
authenticated human without a platform binding remains unbound. A current binding
suspension or grant revocation is observed by the next resolution, even if the
native session is still active. This read snapshot is not durable permission to
mutate: owner commands must still revalidate current authority under their existing
transaction/revision protocol. In-flight command revocation races are not certified
by the read-only proof.

Migration `0034_platform_binding_read` repairs a pre-existing mismatch: the schema
owner of `request_auth.read_platform_identity_bindings(uuid, text)` was subject to
FORCE RLS and therefore hid platform bindings. The function now uses the existing
NOLOGIN, read-only `request_platform_definer`, with only its eight required binding
columns added to the explicit SELECT inventory. It retains exact authority/subject
predicates, platform-only/null-organization filtering and its return schema. Its
search path is pinned, PUBLIC execution is revoked and temporary schema CREATE is
revoked after ownership transfer. No runtime gains direct platform table access,
no RLS policy is widened and no identities, grants or credentials are backfilled.

This is a CONTROLLED definer ownership extension preserving HARD
INV-TENANT-001, INV-AUTHORITY-001 and INV-PRIVILEGE-001. The operation is READ-only:
one statement snapshot, no locks/writes/provider calls, idempotency inapplicable.
Apply the forward migration before enabling the optional composition. Existing
tenant runtime behavior is unchanged; use roll-forward recovery. Real PostgreSQL
proof starts from the supported bootstrap functions, logs in through native auth,
uses separate least-privilege logins, verifies current revocation and rejects
unbound identities and mixed-plane input. Catalog proof retains exact read-only
privileges, private-role topology and ownership checks.

## Private native provisioning API (revision 0035)

`entrypoints.http.platform_control_app.create_platform_control_app` composes
native authentication and Tenancy's provisioning API. It requires three explicitly
supplied session factories: app auth, private platform-authority read and private
platform-control write. The caller owns pool lifecycle and deployment isolation.
Do not mount it into the tenant API or publish it through the ordinary public ingress.
For deployment, use `bootstrap.platform_server:create_app` below rather than
constructing those pools yourself. TLS and ingress limits remain deployment requirements.
OIDC is not required. Every response is `Cache-Control: no-store`.

| Owner operation | HTTP | Capability | Stable operationId |
| --- | --- | --- | --- |
| Create bounded native provisioner | `POST /v1/platform/provisioners` | `platform.tenant_provisioner.provision` | `platform_native_provisioner_create` |
| Create organization and first native controller | `POST /v1/platform/organizations` | `organization.provision` | `platform_native_organization_create` |

Both are Tenancy semantic creation commands, not generic Principal/grant CRUD.
The operator-visible capabilities remain PLATFORM-plane; neither implies tenant
control or operational authority. No agent-tool projection is supplied: this
private human provisioning surface is not an autonomous workload operation.
Architecture classification: CONTROLLED additional entrypoint composition;
HARD module-owned transport and imports through `tenancy.api` remain enforced.

Authentication is a native bearer session resolved through current RE bindings
and authority. `X-RE-Organization-ID` is rejected, even blank; caller-supplied
principal/capability/revision headers cannot establish authority. Current authority
revision is selected by the server and rechecked under the creator Principal lock.
The configured native authority is never accepted from the request body.

Both commands require an opaque `Idempotency-Key` (1-200 characters). A replay
with the same creator/key and normalized intent returns the original IDs with 201;
changed intent returns typed 409. IDs are derived internally, not client-selected
trusted identities. Replay always revalidates the creator and never restores
revoked target grants, bindings or memberships. Organization creation includes a
versioned SHA-256 digest of **all** normalized creation fields in immutable root
provenance, so mutable organization names are not the replay oracle. Its human
provenance reference is limited to 400 characters to fit the complete envelope.

Provisioner input: `native_identity_id`, `provenance_reference` (1-500).
Output: `principal_id`, `binding_id`. The target must be a credentialed native
identity. It receives only non-delegable `organization.provision`, not a platform
controller's other capabilities. Migration 0035 adds the narrow atomic binding
command and nine SELECT columns to the existing private control definer; PUBLIC
and the app runtime cannot execute that command. No role, RLS expansion or
existing-row backfill is introduced; applied migration history remains immutable.

Organization input: `organization_key` (1-120), `display_name` (1-200),
`controller_native_identity_id`, `provenance_reference` (1-400). Unknown fields
are rejected. Output: `organization_id`, `organization_party_id`,
`controller_principal_id`, `controller_binding_id`. The existing native root
function atomically creates the tenant/Party/controller/binding/membership.
The application selects the immutable `tenant-controller-v1` initial policy;
revision 0036 records that selection and adds its 25 explicit grants on root
INSERT only. Provisioner provenance is preserved without making the provisioner
a tenant member. See `initial-controller-policy.md` for the exact authority,
legacy-root compatibility and no-regrant replay contract.

Transaction design: READ authenticated subject and current authority; PLAN
validated intent and deterministic identities; LOCK creator then native identity
using existing private functions; VALIDATE current HUMAN/plane/revision/grants
and target eligibility; WRITE root facts atomically; EMIT durable provenance in
that same transaction. No external network calls occur under authoritative locks.
Same-creator competitors serialize; uniqueness conflicts return 409, stale
authority/deadlock returns `409 platform_authority_changed` for explicit refresh,
ineligible inputs return 422 and missing authority 403. Invalid authentication is
401, mixed-plane input 400. Errors contain no SQL or credentials. An ambiguous
network outcome can be reconciled by replaying the same intent/key.

Protected guarantees: INV-TENANT-001, INV-AUTHORITY-001, INV-PRIVILEGE-001,
atomicity, immutable provisioning provenance and no resurrection on replay.
The DB proof uses independent command connections and observed lock waits; the
HTTP proof begins with the supported one-time deployment bootstrap and never
inserts bindings/tenant roots as test setup. Both run in the current-product lane.
Apply the current Alembic head before enabling this version of the opt-in surface;
its selected v2 controller policy requires additive 0037. Recover by rolling forward.

## Private control-plane process configuration

Run this as a separate private service, never as an additional public tenant router:

```bash
uv run uvicorn request_engine.bootstrap.platform_server:create_app --factory --host 127.0.0.1 --port 8001
```

Required environment variables (provision credentials through the deployment's
secret manager; do not put real passwords in shell history or committed examples):

- `REQUEST_ENGINE_DATABASE_URL`: dedicated app-role login for native authentication.
- `REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL`: separate login with only schema
  USAGE and EXECUTE on `request_platform.read_principal_authority(uuid)`.
- `REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL`: separate login inheriting only
  `request_platform_control`, with no extra direct privileges.
- `REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID`: active native authority UUID.
- Optional `REQUEST_ENGINE_DATABASE_PROBE_TIMEOUT_SECONDS`: default 5, range (0,30].

The factory requires explicit hosts/databases, three distinct usernames and
identical configured host/port/database endpoints. Driver defaults must not select
a different database for each login. Routing/session overrides in URL query parameters
are rejected; normalize aliases in configuration rather than silently mixing
databases. Asynchronous PostgreSQL drivers are required. No external provider,
appointment signing key or identity-exchange key is required by this private service.

Startup and `/health/ready` check all three real database connections with one
bounded overall timeout. Logins must be login-capable, non-superuser, non-BYPASSRLS,
without CREATE ROLE/DB or replication authority. `current_user` must equal
`session_user`. Membership in any unexpected role is rejected even if NOINHERIT.
The app connection cannot execute private platform functions. Read/write connections
cannot access application relations directly (including column grants) or create
objects in application schemas. Read can execute only its one projection; write
can execute only the three explicit provisioning functions and the private
`select_initial_controller_policy(text)` selector. Required
functions must be present and executable, and the owner-selected controller policy
must exist. The private selector validates it transaction-locally without creating
roots or granting authority. This is not an assertion that every
other application's schema, worker or dependency is healthy.

Readiness rechecks native-authority eligibility, selected policy and privilege drift; failures
return generic 503 with no SQL, credentials or catalog details. `/health/live`
reports process liveness independently. Readiness does not terminate the process
or replace ingress/network controls. Pool disposal runs on shutdown and failed
startup. A real-TCP proof covers startup, OpenAPI, native enrollment and unauthenticated
provisioning rejection; real-PostgreSQL cases cover extra role memberships, column
grants, extra callable functions, auth/platform crossover and authority disablement.

## Native authority probe boundary

Migration `0032_native_authority_probe` adds the stable, read-only
`request_auth.is_native_authority_ready(uuid)` projection. Authentication runtime
owns this technical boundary, not tenant business policy. It returns one boolean
for an exact configured ID, never credentials, provider configuration, identities,
bindings or authority grants. Only the app runtime receives EXECUTE; PUBLIC is
revoked, the schema owner owns the definer, and the search path is pinned.
No new direct table privileges are granted. A single statement snapshot is
sufficient: READ only, no authoritative locks, writes, network calls or backfill.
HTTP remains native-first and OIDC remains optional.

This strengthens fail-closed deployment while preserving INV-AUTHORITY-001 and
INV-PRIVILEGE-001. Deploy the additive migration before updating HTTP. Earlier
HTTP builds can coexist but retain their weaker probe until upgraded. Real-role
runtime proofs cover absent/disabled/wrong-kind authorities, active native startup
without an external provider, and authority disablement while serving real TCP.
