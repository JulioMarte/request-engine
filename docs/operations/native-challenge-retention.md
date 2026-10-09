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

The pass is manual and opt-in. It is not scheduled by the application. Configure
a dedicated LOGIN that is a member only of `request_webauthn_retention`
through the deployment's secret/configuration system; use that login only for
this operation. The NOLOGIN caller role can execute the function but has no
table access. Its SECURITY DEFINER owner has only the challenge columns needed
to select eligible rows, DELETE on the challenge table, and UPDATE on `id` only
because PostgreSQL requires an UPDATE privilege for `FOR UPDATE SKIP LOCKED`.
The function never changes that column.

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
