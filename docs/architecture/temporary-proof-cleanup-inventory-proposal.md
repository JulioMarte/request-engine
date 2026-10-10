# Durable temporary-proof cleanup inventory

Status: receipt collection and the bounded destruction/lease worker are implemented.
No production worker is enabled or certified. The worker, admission artifact,
restore protocol and remaining real-provider gates are described in
[`temporary-proof-cleanup-worker.md`](temporary-proof-cleanup-worker.md).

## Implemented collection slice

`0013_temporary_proof_inventory` appends one immutable technical receipt table and
the narrow `request_cmd.record_temporary_proof_retention` primitive. A dedicated
`request_retention_recorder` NOLOGIN group can execute append only, not read
or write tables or mutate business state. Production provisioning must create a
separate restricted LOGIN member and supply its dedicated connection secret.
Receipt rows have forced RLS and owner-only policy, no app/recorder direct grants,
bounded namespace/mount fields and immutable update/delete triggers. Exact duplicate
append is idempotent; conflicting expiry/deletion for the same identity is rejected.
No historical expiry backfill is attempted. Downgrade refuses to drop existing
receipt evidence; stop collection before reverting code/schema.

### Cluster-global role evolution and rollout

`0013` originally created `request_engine_retention_recorder`. That addition
conflicted with accepted `0001`'s exact historical role inventory when installing
a second database in the same cluster. Neither revision nor the baseline loader,
manifest or payload is rewritten. `0020_retention_recorder_role` evolves the
dedicated extension contract to `request_retention_recorder`; this group is
explicitly audited, not ignored merely because its name is outside the baseline
namespace. It remains NOLOGIN, nonprivileged, without role settings, inherited
groups, owned objects or table grants. Only isolated nonprivileged LOGIN members
and the current database's request_cmd USAGE/record primitive EXECUTE are admitted.
Runtime recorder admission also rejects privileged group attributes, administrative
membership and membership in any additional role, including non-Request-Engine roles.

Upgrade the existing database to `0020` **before** installing another database.
With only the legacy group present, rename preserves its OID, memberships and
database ACLs. A new database's unchanged `0013` briefly creates a legacy group;
`0020` admits that convergence only if it has no members, owned objects, unexpected
ACLs or dependencies in another database. It transfers exactly the two local
grants to the canonical group, revokes them from the empty legacy group, and drops
that empty group without CASCADE. Any unexpected dependency aborts the entire
transaction. No user login, credential, table or receipt is deleted. Existing
source database grants and member credentials remain attached to the canonical OID.

If multiple old databases still depend on the legacy role while a canonical group
already exists, the migration fails closed; coordinate their cluster-wide rollout
instead of removing memberships/dependencies to force admission. Ordinary service
deployments and fresh installs must be serialized during this transition. Role
attributes/memberships are cluster-global; ACL auditing is database-local, so each
participating database must pass its own migration/acceptance checks.
`prove_multidatabase_migration_compatibility.py` verifies the second database
reaches the source head with the audited extension and exact append-only ACLs.

Enable collection by supplying both `REQUEST_ENGINE_TEMPORARY_PROOF_BACKEND_ID`
(an explicit operator-assigned deployment UUID, not derived from URL/token) and
`REQUEST_ENGINE_TEMPORARY_PROOF_RECORDER_DATABASE_URL` (async PostgreSQL recorder
connection). Partial configuration fails closed. `build_recovery_secret_store`
wraps the same staging port used by governed recovery, staff invitations and native
recovery delivery; no business endpoint or owner execution path is duplicated.
Provider metadata supplies retained version/creation/deletion; retained staging
expiry supplies business expiry. Older/custom metadata lacking these fields is
rejected when collection is enabled. Recording failures return a safe retryable
error without destroying the possible winner. Without configuration the verified
TTL remains effective, but there is no durable collection claim.

Backend identity must not be reused after mount replacement, restore or namespace
recreation. Merely enabling collection does not certify provider ACLs or authorize
destruction. No scheduler, work/lease table, cleanup result table, janitor LOGIN,
HTTP operation, tool or automatic destroy was added.

## Ownership and retained facts

Owner is platform secret-retention mechanics, not Tenancy authority or Communications
delivery intent. No new administrative HTTP API is needed: this is a technical worker
surface. Business issuance remains on its existing owner APIs, not a second path.

Extend `StagedRecoverySecret` with a distinct typed retained-provider receipt:
backend deployment identity, mount, canonical reference, version, aware creation
and deletion timestamps, and the **retained** business expiry. Populate it from
successful write metadata or the retained CAS winner, never a proposed loser TTL.
Reject missing/malformed receipt metadata before treating staging as successful.

Persist through a separately composed technical recorder immediately after staging
and before any owner transaction acquires authoritative locks. This records orphans
too. Provider I/O and this technical transaction never occur inside the owner
transaction. Failure to record fails issuance closed; leave verified TTL intact
rather than destroy a possible winner. Retry reads the retained receipt and
idempotently appends the same identity.

## Persistence and execution proposal

An append-only `temporary_proof_retention_receipts` table contains backend identity,
mount, reference, version, creation/deletion/expiry timestamps, receipt identity and
recording timestamp. No plaintext, recipient, free provenance, tenant/customer
identifiers or losing candidate expiry. A separate work table contains lease token,
deadline, attempts and reconciliation state; append-only cleanup results record the
exact receipt identity and safe outcome. Uniqueness is backend/mount/reference/
version/creation, rejecting conflicting expiry for one identity. Never infer receipts
from expired intent rows or provider soft-deletion metadata alone.

Dedicated retention-recorder and retention-worker roles receive no business-table
grants. Narrow fixed-purpose `request_cmd` primitives append a validated receipt,
claim expiry plus grace with a fence, and finalize a safe result. No workflow-sized
procedure: Python owns inspection/destruction/reconciliation; PostgreSQL owns facts,
lease/fence CAS and uniqueness. Claims lock only the technical work row, never tenant
or identity topology roots. Provider calls happen after claim commit; a loser cannot
finalize another lease. Never blind-retry unconfirmed destroy: inspect the same
version first. Expired leases permit another inspection, not guessed success.

## Deployment admission

Bind a backend identity to an exact mount and closed temporary namespace. Certify
effective policies for every writer, janitor and ordinary operator. Writer metadata
DELETE and destroy must fail; janitor plaintext reads, writes, recursive LIST and
metadata DELETE must fail. Policy unions can restore an omitted capability. KV-v2
does not support policy parameter constraints; HCL payload rules cannot enforce CAS.
Superuser/break-glass restoration, policy changes, mount replacement and snapshot
restore invalidate admission until fenced and re-certified. This is a deployment
control, not a loopback check. See [OpenBao KV-v2](https://openbao.org/docs/secrets/kv/kv-v2/).

## Migration and proof gate

Expand-only migration after the current head, coordinated with other changes.
Deploy receipt collection before enabling a worker. Historical versions without
trusted retained receipts remain unverified, never guessed/backfilled. Downgrade
first stops worker/recorder; never drop receipt evidence casually.

Required proofs: real PostgreSQL 18 append conflicts, role isolation and lease races;
issuer failure after staging leaves an orphan receipt; CAS winner versus loser TTL;
independently synchronized cleanup/recreation attempts under real provider ACLs;
ambiguous destruction reconciliation; and no secret/reference in ordinary output.
Provider destroy does not prove physical erasure of media/snapshots/backups.

The existing isolated acceptance primitive remains production-blocked until this
proposal is reviewed, implemented and deployment admission is actually proved.
