# Tenant staff administrative history

Status: current additive owner contract. Business owner: Tenancy.

## Operation and privacy gate

`GET /v1/staff/members/{membership_id}/history` (`staff_history_list`) is a
resource Query, not a command or a generic audit API. Current HUMAN `staff.read`
is sufficient for this deliberately minimal projection: that capability already
permits inspecting the target membership and explicit standing grants. History
adds actor Principal UUID, event time, closed command identity and revision numbers;
it adds no capability names, labels, contact, credentials, provider identifiers,
correlation data, arbitrary audit details or provenance/reasons. It must not be
expanded into unredacted audit inspection without a fresh authority/privacy gate.

Input accepts only `after` UUID and `limit` 1..100 (default 50); tenant/actor identity
comes from trusted ActorContext. Each read rechecks current HUMAN active Principal,
active membership and active tenant-control `staff.read` grant in the same statement
snapshot as target, cursor and results. No cached ActorContext is sufficient.

Output is `items` plus nullable `next_cursor`. Each item contains `event_id`,
nullable `actor_principal_id`, `occurred_at` (UTC timestamp), closed `command_name`,
`revision_kind` (`membership`, `authority`, `profile`) and nullable nonnegative
`revision_before` / `revision_after`. Missing or malformed old revisions are null,
not inferred from current state. Profile revision is not authority revision.

Allowed durable sources are the exact target's StaffMembership events for
`staff.invite`, `staff.manage_authority`, `staff.manage_membership`, and
StaffMemberProfile events for `staff.profile.update`. Invitation lifecycle uses a
different aggregate and remains in the invitation workspace; this history does
not claim to reconstruct every authentication or invitation event. Historical
membership creation that left no matching audit row yields no fabricated entry.

Ordering is `(created_at, id)` descending with a deterministic tie-breaker.
The UUID cursor resolves an anchor only among eligible events for this exact
tenant/member/command set. Missing, foreign, another member's and disallowed-event
cursors fail with the same generic `staff_membership_input_invalid` 422. Page size
uses limit+1; an exactly-full last page has no false continuation. New events
appear before the current cursor and require refreshing the first page.

No idempotency key or expected revision applies to a Query. Current authority
failure is 403, absent/foreign membership is opaque 404, malformed inputs are 422,
unauthenticated requests follow canonical 401. Successful data responses are
`Cache-Control: no-store`. No tool projection is added: no machine consumer needs
this human administrative timeline yet.

## Connection, schema and guarantees

HTTP maps transport models into `ListStaffHistoryQuery`; the owner adapter returns
typed application values. One actor-scoped transaction, one SELECT statement,
existing application LOGIN and existing tenant RLS on `audit_records` are used.
No authoritative row locks, mutation, event creation, idempotency write, provider
call or cross-module business dependency is introduced. No new migration/routine/
ACL is necessary; accepted baseline and existing revisions remain unchanged.

Existing audit indexes include tenant/event ID; this first bounded query does not
claim constant-time sorting at arbitrary volume. Measure target history workloads
before adding an aggregate/time index through an appended migration. The schema
and current application grants are not widened speculatively for this projection.

Preserve INV-TENANT-001, INV-AUTHORITY-001, INV-PROVENANCE-001 and
INV-PRIVILEGE-001. PostgreSQL 18 proof reads through a restricted runtime LOGIN,
uses actual commands for audit-generation/replay evidence, checks durable-count
absence of side effects, foreign/missing targets/cursors and revocation after an
ActorContext was constructed. Explicit pre-existing audit fixtures separately
falsify timestamp tie handling, command/aggregate filtering and malformed revision
redaction; they are not evidence that a business command executed.

Canonical proof lanes: Python quality and PostgreSQL current product. Browser
verification, unredacted audit APIs and global user-to-tenant directories are not
implemented or certified by this slice.
