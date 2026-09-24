# Request Engine recovery bundle operations

This runbook covers the machine-executable PostgreSQL + OpenBao backup bundle
used by the P7 disaster-recovery program. It does **not** define an RPO/RTO;
operators must choose and document those values for their deployment.

## Safety contract

A production backup contains both authoritative state systems:

- PostgreSQL custom-format dump;
- OpenBao Raft snapshot.

The plaintext artifacts exist only in a private temporary directory. The final
artifact is encrypted with an age recipient before it is retained. In normal
production mode the command also requires an off-host copy command. A local-only
backup requires the explicit `--local-only` switch and does not satisfy the
off-host backup requirement by itself.

PostgreSQL credentials are read from an environment variable and moved to
libpq's child-process environment; they are not placed in the `pg_dump` or
`pg_restore` command arguments.

## Prerequisites

Install compatible PostgreSQL client tools, the OpenBao `bao` CLI and
`age`. Configure an age recipient whose private identity is stored separately
from the server.

Example environment:

```bash
export REQUEST_ENGINE_BACKUP_DATABASE_URL='postgresql://backup_user:...@db/request_engine?sslmode=require'
export REQUEST_ENGINE_BACKUP_AGE_RECIPIENT='age1...'
export REQUEST_ENGINE_BACKUP_OFFSITE_COMMAND='rclone copyto {artifact} b2:request-engine-backups/{name}'
export BAO_ADDR='https://127.0.0.1:8200'
export BAO_CACERT='/etc/request-engine/openbao-ca.crt'
export BAO_TOKEN='short-lived-operator-token'
```

The OpenBao token used for snapshot operations is an operator credential; do not
reuse Request Engine's bounded runtime AppRole token.

## Create an encrypted off-host backup

```bash
python scripts/operations/recovery_bundle.py backup \
  --output-dir /var/backups/request-engine \
  --local-retention-days <operator-selected-days>
```

Success means all of the following completed:

1. `pg_dump --format=custom`;
2. `bao operator raft snapshot save`;
3. SHA-256 manifest creation;
4. tar packaging;
5. age encryption;
6. configured off-host copy.

A failure in any step returns non-zero. Local retention is optional at the raw
CLI level and must be selected explicitly by production automation. When
`--local-retention-days` is present, pruning runs only after the new encrypted
bundle has been created and the configured off-host copy has succeeded. It only
matches `request-engine-recovery-*.tar.gz.age`; unrelated files are untouched.

The retention value is not an RPO/RTO declaration. Off-host retention must be
configured independently in the storage provider. Do not delete older known-good
off-host backups until the new artifact has been independently verified.

## Verify a backup without restoring

Provide an age identity file from a separate recovery location:

```bash
export REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE='/secure/offline/recovery.agekey'
python scripts/operations/recovery_bundle.py verify /path/to/request-engine-recovery-....tar.gz.age
```

Verification decrypts into a temporary directory, rejects unexpected archive
members and verifies the recorded SHA-256 and byte size for both authoritative
payloads.

## Restore or run a drill

Restore is intentionally destructive and refuses to run unless both conditions
are explicit:

```bash
export REQUEST_ENGINE_OUTBOUND_FENCED=true
export REQUEST_ENGINE_RESTORE_DATABASE_URL='postgresql://restore_user:...@isolated-db/request_engine_restore'
export REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE='/secure/offline/recovery.agekey'

python scripts/operations/recovery_bundle.py restore \
  /path/to/request-engine-recovery-....tar.gz.age \
  --confirm-destructive \
  --evidence-output /var/lib/request-engine/recovery-evidence/restore-20260924.json
```

Use an isolated network/host for a drill. The target Request Engine deployment
must remain outbound-fenced while restored data is inspected. The restore uses
standard `bao operator raft snapshot restore`; it deliberately does not use
force-restore. If seal keys differ, stop and use the documented OpenBao operator
recovery procedure rather than automatically bypassing the seal-key safety
check.

After restore, verify:

- PostgreSQL schema/application reads;
- OpenBao unseal state and expected KV references;
- Request Engine can resolve governed secret references;
- the clone fence still blocks SMTP/webhook/outbox side effects;
- a retained offline Platform Owner recovery code still works when applicable.

When `--evidence-output` is supplied, the command writes the evidence file only
after bundle integrity verification, PostgreSQL restore and OpenBao Raft restore
all complete. The evidence contains timestamps, elapsed restore time, the
encrypted bundle SHA-256, the bundle manifest timestamp and confirmation that the
restore ran with the outbound fence enabled. It contains no database password,
OpenBao token, age identity or secret value.

This file proves that the two authoritative restore operations completed; it does
**not** by itself prove a full recovery drill. The post-restore checks above still
have to be exercised and recorded. In particular, Request Engine reads, governed
secret resolution, clone-fence behavior and offline Platform Owner recovery must
be demonstrated before a drill can be called successful. Observed recovery time
may be recorded from the evidence, but no acceptable RPO/RTO is implied.

Only then may an operator explicitly unfence the restored environment.
