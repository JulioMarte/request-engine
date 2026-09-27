# P7 disaster-recovery acceptance drill

This runbook is the operational acceptance gate for P7-K. A green unit/E2E suite is not a substitute for this drill.

## Preconditions

Use an isolated clean target. Keep `REQUEST_ENGINE_OUTBOUND_FENCED=true` from before restore until clone/staging side-effect tests finish. The backup must be retrieved from the configured off-host destination, not from the source host's local backup directory.

Keep at least one unused Platform Owner offline recovery code outside PostgreSQL and OpenBao. Do not place OpenBao unseal material, the age identity, recovery codes, and the only backup copy on one host.

## Drill

1. Record `backup_completed_at` from the backup being tested.
2. Retrieve the encrypted bundle from the off-host destination and verify it with `scripts/operations/recovery_bundle.py verify`.
3. Record `failure_declared_at`. Destroy or detach the drill source state. Do not reuse its PostgreSQL volume or OpenBao Raft volume.
4. Start empty PostgreSQL and empty production-mode OpenBao Raft storage on the isolated target. Initialize that **disposable target** OpenBao and unseal it with temporary target-only keys so an authenticated operator can apply the snapshot. Do not overwrite or replace the separately custodied **original** OpenBao unseal shares from the source snapshot.
5. Set `REQUEST_ENGINE_OUTBOUND_FENCED=true` and run `recovery_bundle.py restore ... --confirm-destructive --evidence-output ...`. The tool uses OpenBao's forced Raft restore because a clean target has different Shamir/auto-unseal material. Its restore evidence intentionally says `restore_applied_pending_verification`; it is not the final recovery certification.
6. Restart OpenBao after the forced snapshot restore and unseal it with the **original source/snapshot unseal shares**, not the disposable target initialization keys. Verify OpenBao reports the expected restored cluster state. Then recreate Proxy/AppRole machine credentials from retained operator material; do not restore a permanent root token into Request Engine.
7. Start Request Engine against the restored stores. Verify representative PostgreSQL reads and resolve a known governed secret through the runtime `PlatformSecretStore` boundary.
8. While still fenced, create work that would normally cause SMTP/webhook/outbox traffic. Prove no side effect reaches the sink/provider.
9. Stop or make OpenBao unreachable and make SMTP unreachable. Consume one unused offline Platform Owner recovery code to set a new password. Prove the old password fails, old sessions fail, the new password works, the same recovery code cannot be reused, and setup remains closed.
10. Record `service_recovered_at` only after the application reads and governed secret-resolution checks have passed.
11. Create the evidence document below and run `python scripts/operations/recovery_drill_evidence.py evidence.json --output certification.json --max-rpo-seconds <operator-approved-RPO> --max-rto-seconds <operator-approved-RTO>`. Omit the limits only when measuring a drill before targets have been approved; such a measurement is not production RPO/RTO acceptance.
12. Copy the accepted certification to a root/operator-managed read-only path on the control-plane host and set `REQUEST_ENGINE_RECOVERY_CERTIFICATION_FILE` to that file. Restart the private control-plane process. An invalid configured certification is a startup error; absence of the setting leaves backup/restore readiness as `unknown`.
13. Query `GET /v1/platform/readiness` and `GET /v1/platform/observability` with a HUMAN actor holding `platform.readiness.read`. The readiness projection must report `backup_evidence=verified` and `restore_drill=verified`; observability must expose the evidence reference and live (increasing) backup/restore ages. These diagnostics are not authorization state and never contain the recovery code, OpenBao token, SMTP password, secret value, or age identity.

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

`recovery_bundle.py` does not certify recovery by itself. A successful forced Raft restore can still require restart/unseal and post-restore application checks. Only the completed drill evidence below may be promoted to `request-engine/recovery-certification/v1`.

The certification tool calculates observed RPO as `failure_declared_at - backup_completed_at` and observed RTO as `service_recovered_at - failure_declared_at`. It rejects missing proof instead of treating it as false-but-acceptable. When `--max-rpo-seconds` and/or `--max-rto-seconds` are supplied, it also rejects a drill that exceeds those operator-approved objectives and records the accepted limits in the certification. The repository does not define acceptable production RPO/RTO targets: operators must choose and approve those targets for the deployment.

## What this drill does not certify

It does not certify a production SMTP provider. SMTP production acceptance requires real provider credentials and must separately prove DNS/connectivity, certificate validation, AUTH, delivery, provider throttling/error behavior, and the application's UNKNOWN semantics for ambiguous post-transmission outcomes.

It also does not certify off-host durability merely because a local copy command succeeded. `off_host_copy_retrieved=true` means the tested artifact was actually fetched back from storage outside the failed source host.


## Certification ingestion boundary

The control-plane does not search directories or infer recovery success from the presence of backup files. Only an explicitly configured, successfully parsed `request-engine/recovery-certification/v1` document can change the deployment-level recovery diagnostics from `unknown` to `verified`.

The certification is evidence, not authority: PostgreSQL and OpenBao remain authoritative for product state and secret material. Operators may replace the certification after a later accepted drill; the control-plane reads it at process start so the deployment must restart to adopt a new certification. Backup and restore-drill ages continue advancing while the process is running.
