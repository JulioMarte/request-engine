# Admitted temporary-proof cleanup worker

## Current implementation, not production certification

The append-only inventory now has a bounded cleanup consumer. Migration
`0024_temporary_proof_cleanup` adds private technical work and immutable result
tables. It does not enable a process, issue provider credentials, grant business
authority or destroy existing proofs during installation. The accepted baseline,
receipt collection, metadata and retained receipt identities remain unchanged.

Production admission still requires independent real-provider negative policy
evidence. A staging success, loopback URL, configuration flag or unit test is not
that evidence. The worker is off unless an operator deliberately launches the
bounded CLI, releases the default outbound fence, and provides current protected
admission files and isolated credentials.

## Technical ownership and database boundary

`request_proof_cleanup_worker` is a distinct isolated NOLOGIN group, not the
append-only recorder. An isolated LOGIN belonging only to this group has schema
USAGE and EXECUTE on exactly two primitives. It has no private table access,
plaintext read, provider staging, business commands or recorder execution.
The extension namespace, attributes, membership, settings, ownership and current
database ACLs are checked fail-closed during installation. Multi-database proof
also checks the exact current worker grants independently.

`request_cmd.claim_temporary_proof_cleanup` admits only recorded versions for the
specified nonzero backend identity and validated mount after database expiry plus
bounded grace. It materializes at most100 missing work identities and claims one
due work row using `FOR UPDATE SKIP LOCKED`. A random lease token and database
deadline are committed before provider I/O. A claimant cannot release another
token or finalize after its lease expires. `finish_temporary_proof_cleanup`
appends one result for the matching current attempt and closes or defers work;
late or repeated completion returns false without a result. The tables use forced
owner-only row security; primitives have pinned search paths and no PUBLIC execution.

The Python worker closes both database transactions before each provider request.
It reads metadata, compares exact version creation/deletion times with the trusted
receipt, and destroys only that explicit expired version. It never performs LIST,
plaintext GET, metadata DELETE, recreation or a range/all-version destruction.
An ambiguous destroy response is reconciled by metadata, never blindly retried.
A crash after destruction but before completion leaves an expiring lease. The
next holder observes the destroyed version and records completion without another
destroy request. Result facts contain outcome and admission fingerprints, not
plaintext, provider response bodies or copied secret references.

## Admission artifact and restore protocol

The protected JSON artifact has schema `temporary-proof-cleanup-admission/v1` and
an exact closed set of fields: admission/backend UUIDs, provider origin, mount,
fixed recovery namespace, positive grace1..604800seconds, certification start/end
(maximum24hours), and paths/SHA256 bindings for the policy bundle, restore fence
and independent acceptance evidence. TLS is required except literal loopback.
All bindings are rechecked before claim, provider requests and completion.
Operator files must be protected from runtime/API users. Their presence is an
attestation to externally verified facts, not automatic proof that current
effective provider policy is safe.

Before restore, mount replacement, metadata recreation or provider policy changes,
stop workers and revoke janitor credentials. Rotate the fence and backend UUID;
never reuse a backend identity. Re-certify before a new admission. KV-v2 has no
conditional destroy comparing creation identity; a privileged operator who
ignores this stop/revoke protocol can invalidate the safety model. The software
does not claim to contain that operator. Lease fencing protects database results,
not a provider HTTP request already in flight.

Denied/unverified/absent versions close as explicit outcomes, not silent success.
Denied or unverified results require operator investigation; there is no implicit
quarantine reset or history backfill. Existing unrecorded versions remain outside
this worker until a separately reviewed provenance-preserving discovery design.

## Bounded invocation

Use `uv run python scripts/operations/temporary_proof_cleanup_worker.py
--admission <protected-artifact> --maximum <1..100> --enable-admitted-cleanup`.
Supply `REQUEST_ENGINE_RETENTION_WORKER_DATABASE_URL` for the isolated LOGIN and
`REQUEST_ENGINE_RETENTION_CLEANUP_TOKEN` privately through environment. Outbound
effects remain fenced unless `REQUEST_ENGINE_OUTBOUND_FENCED=false` is explicitly
set in the admitted environment. No secret appears in CLI arguments or results.
Metadata inspection additionally has a five-second total deadline and a64KiB
raw response budget, independently of per-chunk client timeouts. Oversized or
compressed metadata is rejected without destruction; a continuously dripping
response returns unresolved and closes its stream. Provider completion facts
remain subject to the current database lease even if an observation finishes late.
Destroy submissions also have a five-second total header/submission deadline;
their response bodies are not consumed. Only subsequent bounded metadata
inspection can confirm completion, including after transport failure or HTTP503.
The client uses five-second timeouts, no redirects, no environment proxy inheritance
and normal TLS verification. The CLI emits only bounded outcome counts and suppresses
exception tracebacks containing private SQL/provider context. Installation does
not create a scheduled task; operational scheduling, protected artifact renewal,
real-provider policy acceptance and restore rehearsal remain deployment gates.
