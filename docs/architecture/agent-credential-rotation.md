# Native agent credential rotation

Owner: Tenancy. Additive pre-production HTTP/DB contract; existing agent lifecycle
and policy remain authoritative. Implementation evidence is recorded separately.

## Operation and journey

`POST /v1/agents/{agent_principal_id}/credentials:rotate`, operation ID
`agent_credential_rotate`, is a semantic Command requiring a current HUMAN tenant
manager with `agent.manage_authority`. It does not project an agent tool: an AGENT
must never rotate its own governance credentials. Authentication supplies caller
and tenant; the path selects the target, not authority. No new grants are seeded.

Send tenant bearer authentication, `X-RE-Organization-ID`, `Idempotency-Key`, and a
closed body containing `expected_authority_revision` (positive), timezone-aware
future `credential_expires_at`, and nonblank `provenance_reference` (at most 400
characters, retained in the secret-free audit). Expiry has no new arbitrary
maximum duration; operators must select it according to deployment policy.

Read `GET /v1/agents/{id}` first. Rotation revokes every stored active native
credential and issues one replacement atomically, advancing authority revision.
It preserves Principal, workload identity, binding, standing grants, profile,
sponsor, policy and lifecycle. Pending/active/suspended profiles may rotate;
rotation never activates a suspended agent. Revoked profiles cannot rotate.
Existing suspension/revocation remains an alternative kill switch, not a missing
feature. Recreating an agent is unnecessary for ordinary credential replacement.

The current manager must still possess delegable operational authority covering
every active agent grant. Possession alone does not establish delegability;
rotation cannot recover an actor outside the manager's current ceiling.

## Retry and lost response

The initial response returns `credential_id`, `authority_revision` and one-time
`workload_token`. Successful responses are `Cache-Control: no-store`. Durable
receipts and audits contain no reusable secret. Same intent/key retries return
the original ID/revision and `workload_token: null`, after current authorization,
target lifecycle, identity and ceiling checks. They never create another token.

For an ambiguous/lost response, retry the same key; use agent inspection's
`credentials` metadata (stored active IDs/status/revision/expiry, never digest or
token) and current authority revision to reconcile. An operator who lost the
secret can explicitly rotate again with a NEW key and current revision, revoking
the unrecoverable credential. Do not blindly retry with new keys. Stored active
status is not proof of usability: expiry, binding, profile and policy also apply.

Failures: missing/invalid authentication 401; current manager/ceiling denial 403;
foreign/nonexistent target 404; stale revision, revoked/unusable target or changed
idempotency intent 409; malformed/naive/past expiry or invalid input 422. A valid
completed receipt can outlive its input expiry without creating a new credential.

## Transaction, connection and migration

HTTP DTO -> typed owner command -> one actor transaction -> narrow PostgreSQL
functions. Forward migration `0025_agent_credential_rotation` follows
`0024_temporary_proof_cleanup`; the immutable baseline is untouched. No provider
I/O occurs under locks. Guards acquire topology share first, current HUMAN
Principal SHARE, then target profile SHARE -> target Principal UPDATE -> workload
identity UPDATE / binding and authority SHARE. Actor membership/grants are read
after its serialized Principal root, without acquiring late Representation/grant
row locks. The target revision is checked before replacement, and SQL repeats
authority checks for direct runtime invocation. Python owns durable idempotency,
token generation, typed audit and transaction orchestration.

Only app EXECUTE on the narrow routines is added, never direct credential table
access. Metadata uses a tenant-qualified, current human-read-authorized definer
projection that cannot return secrets. Required falsification evidence includes
old token invalidation/new token authentication; same-key one effect/null secret;
lost-response reconciliation; stale revision/no credential effect; revoked caller
defeating completed replay; ceiling and foreign-target rejection; independent
transaction races; runtime ACL isolation; real black-box positive agent work,
self-governance denial and immediate suspension. Evidence is not implied by this
design document; pending proofs must remain visible in status reports.
