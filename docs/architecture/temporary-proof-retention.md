# Temporary proof retention in Vault and OpenBao

The technical recovery-secret stores also retain staff invitation proofs. These
bearer proofs are not long-lived platform configuration secrets. PostgreSQL
retains their fingerprint/reference, not their plaintext. Staging runs outside
authoritative database locks and uses KV-v2 CAS zero to preserve one candidate.

## Effective first-version deadline

KV-v2 `delete_version_after` affects **new versions**, not versions already
written. Configure per-key metadata before CAS creation; then verify the actual
version's `deletion_time` from the write response. On CAS conflict, inspect the
retained version's read metadata and verify against its own stored expiry,
not the losing caller's proposed expiry.

The deletion deadline must be timezone-aware, in the future and no later than the
proof's business expiry. A request-timeout/rounding margin makes the provider
deadline slightly earlier than business expiry. Too-short lifetimes fail before
provider I/O; `0s` must never accidentally disable deletion.

Metadata HTTP rejection, transport failure and malformed/unbounded version
deadline are explicit staging failures, not best-effort success. Safe warning
codes `secret_retention_metadata_rejected`,
`secret_retention_metadata_transport_failed` and
`secret_retention_deadline_unverified` identify the failure without recording
credentials, candidate references, recipient addresses or provider response bodies.
Caller-specific retries must retain their ordinary generation/idempotency rules.

Never delete or overwrite a candidate after an uncertain stage or failed
retention verification: another transaction may have retained it. Concurrent
metadata writers can change future-version defaults; verifying the retained
version's actual deadline is therefore mandatory even after a CAS conflict.
Legacy versions with no effective deadline fail closed on staging replay; changing
metadata afterward does not repair their first-version retention.

Provider token ACLs now require create/update permission on the dedicated
temporary namespace's metadata endpoint in addition to CAS writes/read-back.
The existing managed/platform secret namespace must not inherit these TTL rules.

## Soft deletion is not physical destruction

KV-v2 expiry makes a version unreadable through ordinary data reads. It is a
**soft deletion**; privileged undelete, stored encrypted version bytes, snapshots
and backups may retain it. The staging adapter does not prove physical erasure.
See [HashiCorp KV-v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)
for metadata/version semantics and
[KV-v2 lifecycle](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2)
for destroy versus delete.

No automatic expired-proof destroy/purge worker exists in the current adapters.
`discard` deletes all metadata for an explicitly named generation; it is not a
safe substitute for a background retention policy or ambiguous-candidate cleanup.

Required next operational implementation: a dedicated, closed-purpose janitor
for allowlisted temporary-proof prefixes only. It must enumerate version metadata,
require a verified past deletion deadline plus an operational grace period, and
destroy **explicit expired version numbers** (never broad metadata DELETE,
managed platform secrets or a newer version). Use a stable cleanup key and
reinspect version metadata after ambiguous outcomes; report durable/sanitized
cleanup receipts and deadline lag. Legacy unbounded versions require explicit
inventory and operator disposition, not guessed expiry. Test independent competing
stage/cleanup connections and prove a live retained winner cannot be destroyed.
Provider storage/snapshot backup retention and administrative undelete/destroy ACLs
remain separate deployment controls. This proposal is not implemented or certified.

## Focused provider evidence

`scripts/operations/temporary_proof_retention_probe.py` is opt-in. Select an
isolated test Vault address explicitly and provide credentials only through
`REQUEST_ENGINE_RETENTION_PROBE_TOKEN`; never point the probe at production.
It uses a fresh test prefix, verifies the first version's actual deadline,
preservation of its CAS winner and rejection of data reads after soft expiry.
Output intentionally reports `physical_destruction_proven: false` and contains no
proof, provider token or secret reference. Unit tests cover both adapters and
failure/retained-winner cases; real Vault evidence does not certify a real OpenBao
deployment, administrative cleanup or production retention.
