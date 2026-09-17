# Self authority inspection

Status: locally validated on PostgreSQL 18.6 by the assigned validation agent
(see `auth-implementation-status.md`); exact-head GitHub CI remains pending.
Owner: Tenancy.

`GET /v1/me/authority` (`authority_read_self`) is an operational Query protected
by `authority.read_self`. It exposes only the authenticated Principal's active
Representations in the current tenant, with exact scopes, Party IDs, provenance
kind, validity intervals and relationship revisions. Principal and tenant are
never accepted as input. No Party names, contacts or another Principal's grants
are disclosed. Audience: authenticated human, integration or agent operators;
no separate tool projection or execution path is added.

The endpoint requires both effective ActorContext capability and a current
explicit standing operational grant. Temporary delegation alone is insufficient
for this inspection right. Agents additionally need their normal current policy
to allow the read. A caller whose resolved effective capability is absent (for
example after a grant or agent-policy removal) is denied 403 `capability_required`
at the transport gate; a caller that still presents the capability but has no
current standing grant, is inactive, or names a foreign/missing caller is denied
403 `authority_inspection_denied` by the reader. Both are fail-closed; neither
returns an empty success.

Input: bounded `limit` (1..100, default 50) and optional UUID `after`; unknown
query parameters fail with 422. Output: Principal ID, current authority revision,
database observation timestamp, representation page and `next_after`. Pagination
uses ascending representation UUID and reads one extra row to determine whether
another page exists. Pages are live observations, not a frozen session snapshot.
Successful responses use `no-store`; no idempotency key or expected revision is
required because the operation never mutates authority.

This is a relationship inspection, **not** an `allowed=true` oracle for arbitrary
business commands. `requires_owner_validation` is always true. Owner capability,
agent risk, delegation, resource state, relationship expiry and concurrency checks
remain mandatory on invocation. In particular it does not claim to enumerate
resource ACLs or explain every possible booking/queue rejection.

## Resource-effective authority inspection (E3)

`POST /v1/me/authority:inspect` (`authority_inspect_resource`) is the separate,
narrow owner-backed Query for "what is my effective authority for this resource
operation". It is not a broader permission for arbitrary `resource_id`s and it
does not replace `authority_read_self`.

- Capability `authority.inspect_resource` (operator exposure, operational plane,
  query, no idempotency or expected revision) is appended to the immutable
  `tenant-controller-v5` policy by migration `0055`. New roots still select
  `tenant-controller-v3`; existing roots are not backfilled, matching the E1
  policy-upgrade posture.
- Only explicitly supported operations are accepted: `appointments.book` over a
  `subject_party_id` and `booking.manage_supply` over an `authority_party_id`.
  Unknown or unsupported operations fail `422`; an operation/target shape mismatch
  also fails `422`.
- The owning module implements the inspector. Booking resolves the same current
  exact-scope Representation its commands use (`appointments.book` and
  `operations.manage_supply`), in read-only mode via
  `resolve_current_party_authority`, plus the `appointments.subject_override`
  permission for `appointments.book`. Tenancy never reproduces the owner rules.
- The actor organization and principal come from the trusted `ActorContext` only.
  A foreign or absent target and a random identifier both return the same opaque
  `404`; decisions are `allowed`/`denied`/`indeterminate` with reason codes and
  the observed authority/representation revisions. Responses are `no-store`.
- The operation is mutation-free: no locks, no idempotency receipt, no audit or
  outbox write. A decision is advisory and revalidated by the command that acts
  on it.

Connection: owner HTTP DTO -> typed application query/reader port -> app-role
PostgreSQL transaction. READ/VALIDATE only: one statement snapshot verifies the
active caller and explicit grant and projects current active relationships to
active tenant Parties at one database statement timestamp. No authoritative
locks, writes, providers, new definer function or cross-module business imports.
Existing FORCE RLS and tenant predicates apply at every join.

Migration 0038 appends immutable `tenant-controller-v3` = v2 plus the explicit
delegable operational `authority.read_self` grant. New native roots select v3;
old roots and revoked grants are not backfilled, upgraded or restored on replay.
Apply the migration before the new private process; readiness must reject a
missing selected policy. History 0001..0037 remains unchanged. Roll forward.

Protected guarantees: explicit current authority, tenant opacity, immutable
provenance, fail-closed agent policy and mutation-free reads. Required evidence:
real app-role self-only and cross-tenant reads; missing/revoked grant and inactive
caller; revoked/future/expired representations and inactive Parties omitted;
bounded deterministic pagination; no state mutations; HTTP injection/unknown
query rejection; native root reaches the read without manual grants; immutable
v1/v2 and exact additive v3 manifests; existing-root upgrade/replay preservation.
Canonical lanes: Python quality and PostgreSQL current product proof.
