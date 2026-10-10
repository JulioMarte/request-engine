# Native WebAuthn challenge retention

WebAuthn challenges contain only a digest plus ceremony scope and timestamps.
The retention pass removes rows that can no longer authorize an operation. It
never deletes credentials, native sessions, audit/security facts or secrets.

Migration `0037_webauthn_retention` installs the bounded
`request_auth.delete_retained_webauthn_challenges(integer, integer)` function.
The default retention is seven days after the later of expiry and consumption;
the minimum is 24 hours and the maximum is 90 days. Expired-but-still-pending
rows use their expiry timestamp and are eligible only after the same retention
grace. A challenge whose expiry is still in the future is never eligible.
Each call deletes at most 1,000 rows and skips rows locked by concurrent
finalization. The challenge table has no dependent foreign keys or audit facts.

Before applying the migration, drain native-authentication issuance and
finalization traffic for the migration window. It creates a regular index on
the challenge table, so run it with a finite database lock timeout and retry
the migration if the index build cannot acquire its lock promptly.

The application does not schedule the pass. Operators may run it manually or
install the generated systemd service/timer below. Configure a dedicated LOGIN
that is a member only of `request_webauthn_retention` through the deployment's
secret/configuration system; use that login only for this operation. The
NOLOGIN caller role can execute the function but has no table access. Its
SECURITY DEFINER owner has only the challenge columns needed to select eligible
rows, DELETE on the challenge table, and UPDATE on `id` only because PostgreSQL
requires an UPDATE privilege for `FOR UPDATE SKIP LOCKED`. The function never
changes that column.

Run one batch explicitly:

```bash
export REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL='postgresql://...'
uv run python scripts/operations/native_webauthn_challenge_retention.py --execute
```

Optional overrides use integer seconds and rows:

```bash
uv run python scripts/operations/native_webauthn_challenge_retention.py \
  --execute --retention-seconds 604800 --batch-size 500
```

Alternatively set `REQUEST_ENGINE_WEBAUTHN_CHALLENGE_RETENTION_SECONDS` and
`REQUEST_ENGINE_WEBAUTHN_CHALLENGE_RETENTION_BATCH_SIZE`. Values are checked
before connecting; retention must be 86,400–7,776,000 seconds and batch size
must be 1–1,000. Repeat invocations are safe and each invocation is bounded.

## Optional systemd schedule

The renderer creates a oneshot service and persistent calendar timer. Choose
the cadence for the deployment; each run deletes at most one batch, so more
frequent runs may be needed while a backlog drains. systemd will not start a
second instance of an already active oneshot service. The process runs as a
dynamic unprivileged user, has a 90-second start timeout, cannot write to the
installed system tree, and receives its DSN as a systemd credential file rather
than an environment value.
The runner itself uses a five-second connection timeout, a two-second database
lock timeout and a 30-second statement timeout.

Generate the units for the installed checkout and its virtual environment:

```bash
python scripts/operations/render_native_webauthn_retention_systemd.py \
  --on-calendar '<operator-selected-systemd-calendar>' \
  --repo-root /opt/request-engine \
  --python /opt/request-engine/.venv/bin/python \
  --credential-file /etc/request-engine/webauthn-retention.dsn \
  --unit-dir ./generated-webauthn-retention-units
```

The renderer deliberately accepts only conservative path and calendar
characters. It rejects line breaks, shell punctuation, `$` expansion and `%`
systemd specifiers rather than attempting to quote arbitrary input. Validate
the selected schedule and generated units before installation:

```bash
systemd-analyze calendar '<operator-selected-systemd-calendar>'
systemd-analyze verify ./generated-webauthn-retention-units/request-engine-webauthn-retention.service \
  ./generated-webauthn-retention-units/request-engine-webauthn-retention.timer
```

Create `/etc/request-engine/webauthn-retention.dsn` with root ownership and
mode `0600`; edit it through the operator's approved secret-handling path. It
contains only the dedicated maintenance-login PostgreSQL URI, followed by an
optional newline. Percent-encode reserved characters in the URI. systemd loads
this source with `LoadCredential` into a protected runtime credential
directory; the runner reads the file there. Never pass the DSN on the command
line, put it in the generated unit, or include it in incident output. The
renderer does not create credentials or the source file. The scheduled service
uses the script defaults of seven days and 500 rows per pass; set approved
overrides through the unit's non-secret `Environment=` directives only after
reviewing their allowed integer ranges.

After reviewing both generated files and the source credential-file permissions,
install the units, then explicitly reload and enable the timer:

```bash
sudo install -o root -g root -m 0644 ./generated-webauthn-retention-units/request-engine-webauthn-retention.service /etc/systemd/system/
sudo install -o root -g root -m 0644 ./generated-webauthn-retention-units/request-engine-webauthn-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now request-engine-webauthn-retention.timer
sudo systemctl list-timers request-engine-webauthn-retention.timer
```

Activation is a deployment action and is not performed by the renderer or by
this repository change. Confirm the first run's journal output contains only
the deleted-row count or the generic failure marker; it never prints the DSN.
