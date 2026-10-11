# Admin API verification checkpoint — 2026-09-30

Implementation/evidence checkpoint, **not product completion**. Original findings:
[adversarial handoff](admin-api-adversarial-handoff-2026-09-29.md).

## Corrections

- A01/A10: `0006_staff_controller_continuity` evaluates the last-controller guard
  against the grants actually removed by ceiling-preserving replacement. 0005
  preserved outside-ceiling grants but still rejected a no-op on the last controller.
  Preview also reports `missing_apply_authority` for planner-only callers.
  No baseline edit or role expansion.
- A05/A07: the BFF read nonexistent `payload` from the execution view, preventing
  Apply from appearing. It now consumes the actual serialized result, shows the
  permission delta and carries the reviewed revision, reason and desired set into
  Apply, using its real retry form. Tests use actual request DTO schemas.
- A08/A09: absent catalog entries and read transport failures return unavailable;
  failed reads expose no mutation forms. Closed action/UUID validation remains.
- A13: login/setup cookies hold random 256-bit handles only. Encrypted immutable
  server records require an explicitly configured persistent directory. Logout
  removes the record before upstream revocation; old-cookie replay fails. The BFF
  gains no business database authority. Explicit login remains reachable after
  upstream revocation, and supplied login expiry bounds local expiry.
- A15: local PG18.6 upgraded0002→0006 without resetting user data. Launcher checks
  migrations before stopping processes, creates independent cryptographic secrets,
  configures session storage and requires three healthy services. Alembic output
  capture no longer prematurely closes the native process pipeline.

## Executed evidence

- Fresh isolated PG18 `uv run alembic upgrade head`, port55433, database
  `request_engine_admin_verify`: reached0006.
- `uv run pytest tests/db/test_staff_membership_lifecycle.py
  tests/db/test_platform_organization_directory.py
  tests/db/test_runtime_immutable_table_privileges.py
  tests/db/test_runtime_role_topology.py -q --tb=short`: **40 passed**.
- `uv run pytest tests/unit/admin_console -q --tb=short`: **79 passed**, including
  preview→apply exact body/revision/provenance and old-cookie replay after logout.
- `uv run python scripts/ci/ci_jobs.py python-quality`: passed during integration;
  final publication requires managed exact-commit certification.
- Launcher ports8010/8011/8012: runtime/control/console health **200**. Browser
  inspection reached login, not an authenticated journey or real email delivery.

This is not full current-product/Docker E2E or exact-head GitHub CI evidence.
Malformed test prerequisites were corrected, not bypassed: tenant grants require
organization/grantor provenance; async regressions require the asyncio marker.

## Still unfinished — do not mark closed

### Follow-up verification, 2026-10-01

GitHub current-product for `ec00a063` failed the exact application function
privilege inventory: migration 0005 had granted the internal two-argument
controller predicate without a reviewed application read boundary. Python,
Docker E2E and P7 checks passed for that commit; those successes did not make
the failed current-product lane acceptable.

Migration `0007_controller_read_scope` replaces that application grant with
`request_read.staff_controller_is_effective(principal_id)`. Tenancy's reader
uses the new projection. It derives organization/actor from transaction context,
requires an active HUMAN staff planner or authority manager, and checks only the
current tenant. Internal owner commands retain the original predicate. No
persisted facts, command locks or controller semantics change. Coordinated
application deployment is required: an old reader fails closed after upgrade.
Downgrading deliberately restores the previous broader executable surface.

Falsification evidence on isolated PostgreSQL 18, port 55433, database
`request_engine_admin_verify`, upgraded through Alembic to 0007:

```text
uv run pytest tests/db/test_staff_membership_lifecycle.py
  tests/db/test_v3_app_function_privilege_inventory.py
  tests/db/test_runtime_immutable_table_privileges.py -q --tb=short
31 passed
```

The new regression proves a visible local controller, indistinguishable
foreign/missing targets, denial without a local planner, and SQLSTATE 42501
for direct application execution of the internal predicate. The exact reviewed
application inventory now includes only the tenant-bound projection.

The developer PostgreSQL instance on port 5432 (`request_engine_current`) was
also upgraded to 0007 without resetting its data. The canonical local launcher
restarted runtime 8010, control 8011 and console 8012; all reported readiness
200. This health check does not prove an authenticated browser journey.

`uv run python scripts/ci/ci_jobs.py python-quality` passed after this follow-up:
lint, format, type checks, secret/static security scans, dependency audit,
architecture, unit and module tests. Exact-head remote current-product evidence
is still required; the full canonical PostgreSQL runner was not run locally.

Changed-unit semantic disposition: `HEALTHY_AS_IS` (model review, no human
approval inferred). The staff reader remains one owner-local read adapter; its
two changed calls introduce a real privilege boundary, not metric-driven
forwarding. SMTP transport owns transmission-phase outcome classification, so
keeping the new state flag beside the send and exception handling preserves
reasoning locality. Counterargument: the existing planner SQL and transport
branching deserve ongoing review, but extracting them solely for size would not
remove policy or state complexity. Evidence is the diff, complete affected
production units, owner contract, PostgreSQL regressions and passing quality
command; this is not a claim of repository-wide semantic review.

SMTP transmission also had a concrete retry defect: a generic `OSError` during
`send_message` was classified as safe to retry even though the provider might
already have accepted the message. It now returns `UNKNOWN` after transmission
starts; pre-transmission connection refusal remains retryable. This is not
SMTP idempotency or proof of recipient delivery. The transport boundary suite
(`tests/unit/platform/secrets/test_smtp_delivery_channel.py`) passed 14 tests,
including connection reset, broken pipe and generic socket errors during send.

At the 0007 checkpoint, unwired invitation/discovery stubs from interrupted agents were removed rather
than represented as implemented APIs. Their design is preserved below. No
previously supported API was removed; A03 and A14 were still open at that checkpoint.

#### Design checkpoint before implementing A14

The A14 design below is now implemented by 0008; see the current contract in
[`self-organization-discovery.md`](../architecture/self-organization-discovery.md).
The A03 design was unimplemented at that checkpoint. Implementation and current
verification are recorded in the 2026-10-02 follow-up below.

- A14 owner: Tenancy. `GET /v1/me/organizations`, proposed operation ID
  `self_organization_list`, is a self-only, read-only subject-authenticated query
  before tenant materialization, not `staff.read` or platform-owner authority.
  Accept only `after` UUID and bounded `limit`; never accept authority/subject
  identifiers from query/body or a tenant-selection header. Authenticate with
  the existing `HttpSubjectResolver`, require HUMAN, reject recovery-restricted
  sessions. Return only organization id/name and the caller's principal and
  active staff membership identifiers, plus keyset continuation and an explicit
  advisory/owner-revalidation flag. Set `Cache-Control: no-store`.
- Its database projection must join active exact-subject bindings, active
  identity authorities, active HUMAN principals and active memberships, and
  account for native identity/recovery status and organization lifecycle.
  Do not reuse the unrestricted platform organization directory. FORCE RLS
  means a cross-tenant self projection needs an explicitly reviewed definer
  and minimum column grants; do not silently broaden the app role. Test two
  memberships for one subject, foreign subjects, revoked/suspended state,
  pagination, workload/recovery rejection and no implicit authority on selection.
- Mount the subject query through Tenancy's supported API installer. Expose the
  already-built subject resolver from `NativeAuthRuntime` and pass it through
  the canonical HTTP composition; do not invent a second authenticator in the
  BFF. A picker must consume that API and each selected-tenant request must still
  materialize/revalidate its current ActorContext.
- A03 acceptance must authenticate before membership exists and prove possession
  of a single-use invitation token. Native enrollment/login remains canonical.
  Do not equate an email-shaped login handle with verified destination ownership,
  fabricate inviter ActorContext, or fabricate patient Party/contact rows for
  delivery. Plan token-bound CAS/replay and concurrent revoke/resend explicitly.
- Stage the token through the existing governed secret-delivery boundary outside
  DB locks. Persist a digest and opaque secret reference, not plaintext. A
  Communications-owned address-delivery intent must participate in the same
  transaction as invitation creation, with worker fencing and ambiguous-outcome
  reconciliation. A proposed port would record/cancel an intent using tenant,
  invitation id, generation, destination, secret reference/digest and expiry;
  it is not yet an accepted or implemented cross-module contract.
- Acceptance should activate membership without automatic standing grants;
  authority assignment remains the existing preview/apply journey. Revalidate
  inviter authority and identity topology under canonical lock order. Test
  new/existing identities, changed inviter authority, duplicate destination,
  stale revision, token expiry and contested acceptance against PostgreSQL 18.

### A03: email invitations — original open checkpoint

`staff_invite` still uses an existing native identity UUID. It is **not** an email
invitation. No pretend Send button or email field was added to hide that gap.
Required coherent next slice:

1. Tenancy-owned durable StaffInvitation: tenant, normalized destination, inviter,
   expiry, revision, lifecycle, membership correlation and token digest. Append
   a migration; provide bounded list/detail and idempotent create/resend/revoke.
2. Acceptance authenticates a subject independently of tenant membership and proves
   invitation possession. Never link an existing identity merely by matching email
   to login handle. New users use canonical native enrollment/login.
3. Atomically commit delivery intent. Communications currently requires a recipient
   Party/contact, which an unregistered invitee lacks. Introduce a supported
   invitation-delivery contract; do not fabricate a patient Party or copy delivery
   into the BFF. Use governed secret references, fenced delivery and reconciliation;
   no bearer secrets in ordinary audit/outbox payloads or provider I/O under locks.
4. Serialize acceptance with resend/revoke, revalidate inviter authority and tenant
   state, and preserve zero authority before accepted activation. Define replay,
   expiry and foreign-token failures without identity enumeration.
5. Project those same APIs into email draft, delivery status, pending invitations,
   resend/revoke and recipient acceptance. Prove new/existing recipient, revoked
   inviter, duplicate email, stale revision, expired token, concurrent acceptance
   and provider outage with real PG18 and HTTP evidence.

### A14 and product UX

- Platform owner does not imply tenant administrator. Organization directory is
  not self-authorized context discovery. `0008_self_org_discovery` now supplies
  `GET /v1/me/organizations` from a verified HUMAN subject before tenant selection.
  `/my-organizations` projects that API and links to the existing staff workspace;
  it never supplies a tenant header during discovery or grants authority on selection.
- PostgreSQL evidence covers exact subject, active lifecycle boundaries, two
  memberships, foreign/missing identities, alternative active bindings and HTTP
  composition through a real application LOGIN. HTTP tests also deny caller-supplied
  subject/authority/tenant input, workload and recovery-restricted sessions. BFF
  tests verify read-only runtime forwarding, pagination, malformed/error/empty
  responses and no membership links after failed reads. No authenticated browser
  or actual provider-email proof is claimed.
- Exact-head CI on `aef7dbb4` exposed missing isolation probes for `staff.overview`
  and `staff.authority.plan`, plus the old 23-grant Instance Claim expectation.
  The probes now exercise those endpoints with unchanged durable-state assertions.
  Claim evidence expects the v4 policy's 24 grants and explicitly verifies active,
  nondelegable `platform.organization.read`. The two isolation probes passed, and
  the full HTTP setup/claim case passed locally on isolated PG18.
- A14 integration evidence: `uv run pytest` over
  `tests/db/test_self_organization_discovery.py`, `test_staff_membership_lifecycle.py`,
  `test_platform_definer_topology.py`, `test_runtime_immutable_table_privileges.py`
  and `test_v3_app_function_privilege_inventory.py`: **47 passed** on PG18,
  port 55433, `request_engine_admin_verify`, revision 0008. The unusable-context
  fixture now uses ordinary staff alongside a surviving controller, not an
  impossible disabled last-controller world; it preserves revision/session-epoch
  guards. Credential verification is substituted in the HTTP composition case,
  but the owner reader executes through a real restricted app LOGIN.
- `uv run python scripts/ci/ci_jobs.py python-quality` passed for the integrated
  A14 work. The developer DB on port 5432 was upgraded to 0008 without resetting
  data; the launcher reported all three services ready. Live runtime OpenAPI
  advertises `self_organization_list` with bearer security; anonymous runtime
  discovery returns 401 and console discovery redirects to login (303).
- Final narrow rerun: `tests/db/test_self_organization_discovery.py`: **10 passed**;
  `tests/unit/admin_console` plus `tests/unit/test_self_organizations_http.py`:
  **100 passed**. The frontend-design review retained the existing restrained
  admin layout and added explicit empty/error states, accessible navigation and
  a return path to organization selection instead of a second permission model.
- Staff remains identifier-oriented. Names/contact metadata require explicit
  privacy-reviewed API projections, not invented dashboard metrics.
- Permission input now uses checkboxes projected from the API's delegable ceiling;
  existing assignable grants are preselected and outside-ceiling grants preserved.
  This is not a complete localized permission-description catalogue or role model.
- Real WebAuthn/browser retry and production email delivery require separate E2E
  evidence. HTML unit assertions are not browser proof.
- A12 intentionally retains global native-session revocation on tenant suspension,
  with disclosure and existing cross-tenant proof; policy was not changed here.

## Session deployment and semantic review

`REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY` is required. Unix mode0700;
Windows ACL restricted to service identity. Workers/replicas share persistent
volume and secret; independent replica disks are unsupported. No ephemeral fallback.
Local launcher rotates its secret on restart, invalidating old sessions. Bounded
login cleanup is not a complete production retention service.

Session storage is a cohesive technical credential boundary; staff reader/routes
retain existing ownership. No forwarding modules or SQL splitting just to reduce
size metrics. No independent human approval or production certification is claimed.

## Follow-up implementation, 2026-10-02 — A03

The owner contract is now
[`staff-email-invitations.md`](../architecture/staff-email-invitations.md).
Migration `0009_staff_email_invitations` appends durable tenant invitations and
Communications delivery intents. The immutable baseline is unchanged. Six owner
operations create/list/read/resend/revoke/accept invitations; administrative
commands use idempotency and revisions. Acceptance requires a real native session
and the expiring proof, not a matching email handle or an impersonated inviter.
It creates an active membership with **zero grants**. Existing identity links
require administrator review rather than being revived by another invitation.

The console projects those operations, including enrollment/login through native
authentication, signed CSRF protection and a fragment-only proof cleared from the
URL. Acceptance does not automatically redirect to an admin-only staff workspace:
membership alone does not confer `staff.read`. API and worker use the same governed
store. The API stages proofs without installation-wide SMTP-read privileges;
the worker resolves managed SMTP or an explicit fallback and records its outcome.
No patient/contact rows are fabricated. Uncertain submission is reconciled rather
than blindly resent. SMTP acceptance is not inbox receipt. Revocation invalidates
the proof but cannot recall a network send already in flight.

Executed integration checkpoint:

```text
PGHOST=127.0.0.1 PGPORT=55433 PGDATABASE=request_engine_admin_verify
PostgreSQL 18.6 (180006), UTC, btree_gist 1.8; Alembic head 0009
uv run pytest tests/db/test_staff_email_invitations.py
  tests/db/test_staff_invitation_delivery.py
  tests/db/test_platform_definer_topology.py
  tests/db/test_v3_app_function_privilege_inventory.py
  tests/db/test_self_organization_discovery.py
  tests/db/test_staff_membership_lifecycle.py -q -m postgres --tb=short
66 passed in 402.04s
```

This checkpoint preceded the more specific existing-link error mapping and the
staging-only API composition. After those changes, the invitation suite reran:
**15 passed in 92.09s**, including the specific HTTP 409 code/action and absence of
extra membership effects. The suite uses real native enrollment/password login
and restricted application sessions; only the external secret provider is
substituted. Independent connections synchronize acceptance against resend/revoke
and observe actual lock waits. Proof/GUC forgery, direct accepted-state writes,
withdrawn inviter authority and a revoked-session race are rejected. Delivery
proof covers atomic rollback, generation replay, tenant opacity, cancellation,
lost leases and unknown-outcome reconciliation without duplicate publication.

The canonical `scripts/ci/run_current_product.sh` was attempted. Migration-head
verification and schema catalog/analysis ran; the runner then failed at its
Docker-backed clean-baseline installation because the local Docker engine pipe
was unavailable. It did **not** complete. The isolated portable PG18 cluster is
not the developer Docker database on port 5432; that database has not been updated
to 0009 during this follow-up. No existing developer data was reset.

Additional executed proof: the five invitation cases in
`tests/e2e/test_http_tenant_isolation_matrix.py -k 'staff.invitation'` passed
(`5 passed, 62 deselected`, 37.29s). This exposed and fixed an unmapped PostgreSQL
authority denial during pre-staging replay checks: create/resend now return the
typed 403 instead of an internal error. All five outcomes preserve durable state.
The full `python-quality` command passed after this correction, including Ruff,
Pyright, secret/static-security scans, dependency audit, architecture, unit and
module tests. The subsequently added expiry regression received targeted type/lint
checks and PostgreSQL execution; publication still requires exact-SHA certification.
Panel/API/secret tests passed `103` cases, and `node --check` accepted the invitation
script. None of these assertions is a browser execution claim.

The final invitation suite expanded to **16 passed in 93.73s**, adding actual
expiry, replacement of an expired destination, stale-revision rejection and
conflicting idempotency. A subsequent provenance review found that resend/revoke
reasons were validated but not retained in audit details. The corrected commands
persist their supplied reason; acceptance retains the original invitation reason
and the database rejects rewriting that original value. After reinstalling only
the unpublished 0009 draft on the verified-empty isolated database, the invitation,
delivery, platform-definer and app-function inventory suites passed **30 cases in
136.58s**. The immutable 0001 payload and developer database were not modified.

Next journey improvement: an invitation email currently describes the organization
generically. Add a proof-bound recipient preview through a Tenancy-owned API to
show the organization and expiry before acceptance; never put the proof in a GET
query or infer identity from its email address. This is not implemented in A03.

Still unfinished: complete canonical/Docker evidence and exact-head remote CI,
authenticated browser/JavaScript journey and real provider/inbox proof. Acceptance
is native-only, not OIDC. The email policy intentionally accepts one ASCII mailbox,
not display names, lists, quoted local parts or internationalized addresses.
Names/contact metrics and a localized permission/role catalogue remain separate
privacy/product work; the reference screenshots are not fully implemented.

### Exact-head CI follow-up: documentation and topology entry

Published checkpoint `73993348` failed the normative worker-documentation change
contract. `448e008f` added the ScheduledAction invitation runtime, provider
ambiguity and credential-boundary documentation without disabling that contract.
Python quality, Docker E2E, observability, configuration and recovery simulation
passed remotely at `448e008f`. Current-product PostgreSQL stopped with **379 passed,
1 failed**: the complete identity-topology writer inventory did not yet include
`request_cmd.materialize_invited_staff`. Its first statement delegated to the
proof/session lock function, which takes the shared topology gate; the stronger
direct-entry contract requires acquiring that gate in the writer itself.

The correction appends `0010_invitation_topology_gate`, rather than rewriting
published 0009. It replaces only the function body, adding the direct gate as
its first statement while preserving proof/session checks, owner, pinned search
path, grants, atomic zero-grant materialization and provenance. No table data
backfill or new execution privilege is introduced. The inventory now classifies
this writer and the existing independent-connection proof executes its
eight-argument entrypoint. No gate-order or lock-absence assertion was removed.
The owner contract documents upgrade/downgrade and compatibility consequences.

Local re-proof on isolated PostgreSQL 18.6 at port 55433 passed:

```text
uv run pytest tests/db/test_identity_topology_gate.py
  tests/db/test_staff_email_invitations.py -q -m postgres --tb=short
50 passed in 329.14s
```

The forward migration was then downgraded to 0009 in that isolated database.
The strengthened writer-inventory test failed as expected on the delegated
first statement (1 failed, 5.46s). Upgrading back to 0010 succeeded. The same
inventory, independent-connection entrypoint blocking, platform-definer topology,
app-function privileges and invitation-delivery proofs then passed **16 tests in
97.56s**. This verifies rollback/roll-forward plus a real falsifier, not only a
changed inventory list. Developer port 5432 was not modified.

The complete `python-quality` command passed against the clean exact commit
`12e55a542fdcbb705641841d25681094822dc1e3`; baseline/diff generation and both
quality-evidence/v2 packets were finalized and schema-validated at that SHA.
Remote exact-head re-proof remains required. Neither the failed remote run nor
its downstream prerequisite failure counts as a successful current-product lane.
