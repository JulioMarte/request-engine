# P7 disaster-recovery acceptance drill

This runbook is the operational acceptance gate for P7-K. A green unit/E2E suite is not a substitute for this drill.

## Preconditions

Use an isolated clean target. Keep `REQUEST_ENGINE_OUTBOUND_FENCED=true` from before restore until clone/staging side-effect tests finish. The backup must be retrieved from the configured off-host destination, not from the source host's local backup directory.

Keep at least one unused Platform Owner offline recovery code outside PostgreSQL and OpenBao. Do not place OpenBao unseal material, the age identity, recovery codes, and the only backup copy on one host.

## Drill

1. Record `backup_completed_at` from the backup being tested.
2. Retrieve the encrypted bundle from the off-host destination and verify it with `scripts/operations/recovery_bundle.py verify`.
3. Record `failure_declared_at`. Destroy or detach the drill source state. Do not reuse its PostgreSQL volume or OpenBao Raft volume.
4. Start empty PostgreSQL and empty production-mode OpenBao Raft storage on the isolated target.
5. Set `REQUEST_ENGINE_OUTBOUND_FENCED=true` and run `recovery_bundle.py restore ... --confirm-destructive --evidence-output ...`.
6. Recreate OpenBao Proxy/AppRole machine credentials from retained operator material; do not restore a permanent root token into Request Engine.
7. Start Request Engine against the restored stores. Verify representative PostgreSQL reads and resolve a known governed secret through the runtime `PlatformSecretStore` boundary.
8. While still fenced, create work that would normally cause SMTP/webhook/outbox traffic. Prove no side effect reaches the sink/provider.
9. Stop or make OpenBao unreachable and make SMTP unreachable. Consume one unused offline Platform Owner recovery code to set a new password. Prove the old password fails, old sessions fail, the new password works, the same recovery code cannot be reused, and setup remains closed.
10. Record `service_recovered_at` only after the application reads and governed secret-resolution checks have passed.
11. Create the evidence document below and run `python scripts/operations/recovery_drill_evidence.py evidence.json --output certification.json`.

## Required evidence schema

```json
{
  "schema": "request-engine/recovery-drill/v1",
  "bundle_sha256": "<64 hex characters>",
  "backup_completed_at": "2026-09-26T20:00:00+00:00",
  "failure_declared_at": "2026-09-26T20:30:00+00:00",
  "service_recovered_at": "2026-09-26T20:45:00+00:00",
  "proofs": {
    "postgres_restored_from_bundle": true,
    "openbao_restored_from_bundle": true,
    "bundle_integrity_verified": true,
    "off_host_copy_retrieved": true,
    "clean_environment": true,
    "outbound_fenced_during_restore": true,
    "clone_side_effects_blocked": true,
    "request_engine_reads_verified": true,
    "governed_secret_resolution_verified": true,
    "platform_owner_offline_recovery_with_openbao_down": true,
    "platform_owner_offline_recovery_with_smtp_down": true,
    "old_password_rejected": true,
    "old_sessions_rejected": true,
    "recovery_code_reuse_rejected": true,
    "setup_remained_closed": true
  }
}
```

The certification tool calculates observed RPO as `failure_declared_at - backup_completed_at` and observed RTO as `service_recovered_at - failure_declared_at`. It rejects missing proof instead of treating it as false-but-acceptable. The repository does not define acceptable production RPO/RTO targets: operators must choose and approve those targets for the deployment.

## What this drill does not certify

It does not certify a production SMTP provider. SMTP production acceptance requires real provider credentials and must separately prove DNS/connectivity, certificate validation, AUTH, delivery, provider throttling/error behavior, and the application's UNKNOWN semantics for ambiguous post-transmission outcomes.

It also does not certify off-host durability merely because a local copy command succeeded. `off_host_copy_retrieved=true` means the tested artifact was actually fetched back from storage outside the failed source host.
