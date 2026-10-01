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
