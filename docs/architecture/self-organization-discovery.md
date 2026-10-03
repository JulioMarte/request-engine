# Self-only organization discovery

Status: current contract. Owner: Tenancy. Added by `0008_self_org_discovery`.

## Operation and authority

`GET /v1/me/organizations` (`self_organization_list`) lists the authenticated
HUMAN subject's active organization memberships before tenant selection.
It is a Query, not an authority mutation or platform organization directory.
No tenant capability is required: requiring one before discovering the tenant
would make onboarding circular. Exact-subject authentication and the owning
read projection are the authorization boundary. Workload and recovery-restricted
sessions are rejected. Native and configured OIDC authentication retain their
existing verification path; the HTTP input cannot supply a subject or authority.

- Inputs: `after: UUID | null`, `limit: 1..100` (default 50). Other query fields
  and `X-RE-Organization-ID` are rejected. No request body or principal selector.
- Output: `items` containing organization id/name, the subject's principal id
  and staff membership id; `next_after`; `requires_owner_validation: true`.
- Pagination: organization UUID keyset, read one extra row to detect continuation.
  Results are advisory snapshots; memberships may change between pages.
- Idempotency/revision: no key or expected revision for this read. Choosing a
  result grants nothing; every subsequent owner command revalidates its current
  ActorContext, capability, relationship and revision policy.
- Failures: 401 missing/invalid or non-HUMAN authentication; 403 restricted
  recovery; 400 tenant-selector header; 422 invalid pagination/extra fields.
  Valid authenticated subjects without usable memberships receive an empty list.
- Cache: successful responses use `Cache-Control: no-store`. No bearer,
  password, login handle, other members or standing grants are returned.
- Tool projection: none. This is a HUMAN authentication/context-selection
  surface, not an agent capability. No duplicate operation/policy registry.

## Persistence and connection boundary

`PostgresSelfOrganizationReader.list_for_subject` calls
`request_auth.read_self_organizations(authority, subject, after, limit)` in one
read transaction. Authority and subject come only from `HttpSubjectResolver`.
As with existing authentication resolution functions, these arguments belong
to the trusted server boundary, not public SQL or model-controlled HTTP inputs.

The SECURITY DEFINER read uses existing `request_platform_definer`, pinned
`search_path`, no PUBLIC execute, and only eight additional column-level reads
on identity authorities, principals and staff memberships. The application role
gets execute on this read, not broader table access. FORCE RLS is not disabled.
Exact function ownership and column grants are covered by the definer inventory.

The projection requires an exact active tenant identity binding, active identity
authority, active HUMAN principal, active staff membership and operationally
active organization. Native bindings also require an active native identity.
Any active binding of the member may discover the organization; the membership's
original establishment binding is not its only legitimate sign-in path.
Platform membership alone grants no result. Inactive organizations remain in the
separately authorized platform directory, not this usable-context picker.

There are no writes, authoritative locks, external I/O, audit/outbox effects,
backfills or implicit grants. Upgrade is additive. Downgrade removes the function
and only the newly added read privileges. Existing authentication/session and
global revocation semantics are unchanged. Guarantees preserved: tenant opacity,
least privilege, no caller-manufactured authority and owner revalidation.

## Admin projection and evidence

`/my-organizations` reads the operation from runtime OpenAPI and calls that API
without a tenant header. It does not use the platform directory or query the
database. Cards/navigation link to the existing tenant staff workspace; failed
reads show no membership links, and an empty valid result explains next steps.
API pagination and response shape are validated before rendering. The chosen
organization is encoded in the workspace URL, not treated as authorization or
stored as a new global session entitlement.

Evidence lives in `tests/db/test_self_organization_discovery.py` (real PG18 and
HTTP composition over an app LOGIN), `tests/unit/test_self_organizations_http.py`
(subject boundary and DTO rejection), and
`tests/unit/admin_console/test_my_organizations.py` (HTTP-only projection,
pagination, empty/error states and no browser-supplied authority forwarding).
The DB suite is part of `scripts/ci/run_current_product.sh`. HTTP composition
tests substitute credential verification only; they do not claim a real
WebAuthn browser journey. Email invitations are a separate unfinished capability.
