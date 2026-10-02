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

No automatic or production expired-proof destroy/purge worker exists.
`discard` deletes all metadata for an explicitly named generation; it is not a
safe substitute for a background retention policy or ambiguous-candidate cleanup.

## Closed-purpose isolated cleanup acceptance

`platform/secrets/temporary_proof_cleanup_acceptance.py` implements an **isolated acceptance
primitive**, not a certified production janitor. The primitive itself requires
explicit `isolated_acceptance=True`, a literal loopback provider URL and redirects
disabled. The opt-in CLI `scripts/operations/temporary_proof_cleanup_acceptance.py` additionally
requires `--allow-isolated-destroy`. Never use either against production, including
a production service forwarded onto loopback.
Loopback and opt-in are admission guards, not evidence of isolation: the operator
must independently select a disposable development/test server and ensure no
production tunnel or forwarded production namespace is involved.

The only allowed reference shapes are
`request-engine/identity-recovery/<UUID>/<positive-generation>` and
`request-engine/temporary-proof-retention-probe/<UUID>/<UUID>/<positive-generation>`.
Current bootstrap uses identity-recovery for both recovery and invitation proofs.
Custom configured prefixes are deliberately unsupported; the managed/platform
namespace is never admitted. There is no recursive LIST or metadata DELETE.

Input is a trusted operator inventory of retained-version receipts, each containing
`reference`, explicit `version`, aware `created_at`, `deletion_at` and business
`expires_at`. The last value must come from the **retained** staging receipt,
not a losing candidate, a guessed timeout or provider soft-deletion metadata.
Current staging does not persist this cleanup inventory automatically. Metadata
must independently match receipt creation and deletion timestamps. Missing,
malformed or unbounded deadlines are skipped, not repaired or guessed. Manual
soft deletion cannot substitute for verified business expiry. Both business expiry
and provider deletion deadline must have passed plus a positive grace period.

Only the explicit version number is submitted to KV-v2 `destroy`. After any
response or transport ambiguity the primitive reinspects the same version. A
confirmed destroyed version is retry-safe; an unconfirmed result is `unresolved`
and must be reconciled by a later inspection, not reported as success. Results
contain only a SHA-256 cleanup identity and outcome; no token, proof, address,
reference or provider response body. CLI output can be saved as an operator receipt
but is not automatically durable audit storage. Default CLI grace is one hour;
that is an acceptance-tool default, not a certified production retention policy.

### HARD production blocker: same-version reuse

KV-v2 `destroy` has no compare-and-swap precondition. Between inspection and
destruction, another actor could DELETE key metadata and recreate version 1.
Reinspection detects mismatched creation time **after** the new winner has already
been destroyed. Current recovery stores' `discard` can delete key metadata, so
namespace/version non-reuse is not presently an enforceable system invariant.
The regression suite includes this counterexample; it does not claim that a
green counterexample proves safety. Preserving a live newer version 2 is proven,
but does not establish safety for recreated version 1.

Production cleanup therefore remains blocked pending an explicit redesign:
remove metadata DELETE/recreation from ordinary writers and `discard`, establish
non-reused generation/version identities, prove deny-delete ACLs for **all**
participating writers (including operators), or provide an atomic provider surface.
Then acquire trusted retained-version expiry inventory and add independently
synchronized recreation/cleanup concurrency evidence. Do not enable a scheduler
or weaken the HARD live-winner invariant merely to finish retention.

### Technical connection gate

Owner: platform secret-retention mechanics; no new business capability, HTTP
operation, tool projection or Tenancy authority. Caller: explicitly selected local
acceptance CLI/probe; input: validated temporary-version expiry receipts.
Authentication: operator-supplied provider credential via
`REQUEST_ENGINE_RETENTION_CLEANUP_TOKEN`; authorization: ordinary KV-v2 read-metadata
and explicit-version destroy ACL, never bypassed. No PostgreSQL transaction,
locks, outbox or cross-module reads occur. Provider I/O uses the CLI's five-second
timeout; only GET metadata and POST destroy are needed. Reconciliation precedes
any later repeated destroy. The stable cleanup identity names one reference,
version and creation timestamp, not a batch or newly discovered resource.

Provider encrypted storage/snapshots/backups, privileged undelete/destroy access,
receipt provenance/durability, deadline-lag monitoring and production scheduler
ownership remain separate unresolved deployment controls. KV-v2 destroy confirms
provider version destruction, **not physical erasure of media or backups**.

## Focused provider evidence

`scripts/operations/temporary_proof_retention_probe.py` is opt-in. Select an
isolated test Vault address explicitly and provide credentials only through
`REQUEST_ENGINE_RETENTION_PROBE_TOKEN`; never point the probe at production.
It is loopback-only and uses a fresh test prefix. It verifies the first version's
actual deadline, preservation of its CAS winner, rejection of data reads after
soft expiry, and exact-version destroy/reinspection/idempotent reconciliation.
Select `--provider vault` or `--provider openbao` explicitly.
Output intentionally reports `physical_destruction_proven: false` and contains no
proof, provider token or secret reference. Unit tests cover both adapters and
failure/retained-winner cases. Isolated dev-server probes passed on Vault 1.21.0
and OpenBao 2.6.1; these are focused KV-v2 acceptance results, not production ACL,
administrative cleanup, recreation-race safety, backup policy or deployment certification.
