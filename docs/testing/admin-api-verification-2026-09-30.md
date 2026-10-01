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

Unwired invitation/discovery stubs from interrupted agents were removed rather
than represented as implemented APIs. Their design is preserved below. No
previously supported API was removed; A03 and A14 remain open.

#### Next implementation boundaries (not implemented)

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

### A03: email invitations

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
  not self-authorized context discovery. Add the subject-bound query before an
  unrestricted tenant picker.
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
