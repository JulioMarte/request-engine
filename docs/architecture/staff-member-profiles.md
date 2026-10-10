# Tenant staff member profiles

Status: current additive contract. Business owner: Tenancy.

## Product and operation gate

A staff display name is a tenant-local administrative label, not verified identity,
a login handle, an email address, a Party or a global account profile. The same
person may use different labels in different organizations. Existing memberships
start with `display_name: null` and `profile_revision: 0`; no invented-name backfill
is performed. The current organization context already scopes every staff result.

- Resource command: `PATCH /v1/staff/members/{membership_id}/profile`.
- Stable operationId: `staff_profile_update`; owner: Tenancy.
- Capability: existing current HUMAN `staff.manage_membership`, explicitly extended
  to administrative member labels, without granting additional authority.
- Input: nullable `display_name` (trimmed 1..200 characters, no control characters),
  `expected_profile_revision` (0 for absent profile), `provenance_reference` (1..500).
- Output: new `profile_revision`; `staff_list` / `staff_get` project name and revision.
- Idempotency: required key; same fingerprint replays the original revision, not
  the latest name. Different fingerprints conflict. Replay still rechecks current
  management authority and target visibility. Self-label changes are permitted.
- Concurrency: independent profile revision; no membership/authority revision changes.
- Failure: 403 current manager denial, 404 absent/foreign member, 409 stale revision
  or terminal revoked membership, 422 malformed transport fields.
- No tool projection: a human directory label is not yet an agent operation.

`staff_list` additionally accepts optional `search` (1..100 trimmed characters),
matching a literal case-insensitive substring of the tenant display name only,
using PostgreSQL's built-in `pg_unicode_fast` collation for casing independent
of the host's default C/operating-system locale.
Percent/underscore are literal characters, not wildcards. Search and membership
status filters precede UUID ordering and bounded limit; counters remain tenant-wide.
No contact, credential, login-handle or cross-tenant directory search is implied.

## Persistence and connection gate

`0011_staff_member_profiles` adds the profile table, a composite membership FK,
FORCE tenant RLS, column-level application SELECT and two narrow definer primitives.
The app receives no profile INSERT/UPDATE/DELETE or broad new table privileges.
No external provider, cross-module connection, event or ScheduledAction is involved.

Python owns validation, command fingerprint, transaction, idempotency and append-only
audit. PostgreSQL owns bounded target locking, current-authority checks and profile
CAS/upsert. Protocol: READ input; PLAN label; LOCK idempotency identity (the existing
staff-command order), then ordered active staff root, current
manager principal/membership/grant, then target membership/profile; VALIDATE tenant,
HUMAN/current manager, non-revoked target and profile revision; WRITE profile only;
EMIT one profile audit and idempotency result in the same transaction. Audit contains
revisions and reason/provenance, never display-name plaintext. Rejected/replayed
commands append no audit. No authoritative network I/O occurs under these locks.

The identity-topology advisory gate is not acquired: no binding, principal, standing
grant, membership status or authentication reachability is written. Ordered staff
root locks keep the connection compatible with existing authority/lifecycle commands;
manager row SHARE locks prevent revocation from committing across an accepted edit.

Compatibility is additive, without data migration/backfill. Downgrade removes only
these new routines/table and composite FK support; it loses new profile labels.
Accepted baseline and already published revisions are unchanged.

## Guarantees and falsifiable evidence

Preserve INV-TENANT-001, INV-AUTHORITY-001, INV-ATOMICITY-001, current idempotency
and provenance guarantees. Profile revision is not authority. PostgreSQL 18 tests
exercise actual runtime commands/reads, stale updates, key replay/conflict, current
authority revocation, foreign-row opacity, direct DML denial, literal search before
limit and independent contested updates. Module/unit tests cover typed transport,
normalization and denial before DB access. Canonical lanes: Python quality and
PostgreSQL current product proof. Browser and usability proof remain separate.

## Membership list pagination

`staff_list` remains a HUMAN `staff.read` Query with the same HTTP path, input
limit 1..100, filters, failure semantics and tenant authority. No idempotency key
or revision is introduced. The owner returns typed `StaffMembershipPage` rather
than requiring the HTTP adapter to infer continuation from a full page.
The SQL reader applies status/literal-name filters before fetching limit+1 rows,
returns at most the requested limit, and publishes a cursor only when a further
matching row exists. An exactly-full terminal page has no continuation; an empty
page has neither items nor cursor. This uses the existing one-statement authority
snapshot and does not introduce writes, providers, new ACLs or schema changes.
