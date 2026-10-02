# Admin console

Private operator panel that projects the platform control-plane HTTP API. It is a
separate entrypoint and process; it owns no business logic, holds no database or
OpenBao connection, and introduces no second execution path. Every action is an
HTTP call to the control plane, which keeps capability and step-up authority as
the single source of truth.

Tenant staff administration uses the configured `runtime_api_base_url` and the
same stored HUMAN bearer. **My organizations** (`/my-organizations`) consumes
`GET /v1/me/organizations` without a tenant header; it does not use the platform
directory as proof of access. Opening a listed workspace still requires the
tenant API's staff permissions. The console has no independent tenant grants.

## Design

```text
browser  --(same-origin, HttpOnly console cookie)-->  admin console
admin console  --(server-to-server Authorization: Bearer)-->  control plane
control plane  -->  PostgreSQL / OpenBao / providers
```

- Browser cookies contain only random opaque handles. Login and setup bearers
  live in encrypted immutable records in a private persistent directory. Logout
  deletes the server record even when upstream revocation fails. All workers and
  replicas must share that directory and encryption secret. Unix permissions
  must be 0700; on Windows restrict the directory ACL to the service identity.
  There is no ephemeral or credential-in-cookie fallback. Rotating the secret
  invalidates existing sessions. This store grants no business-database access.
- The browser talks only to the console origin, so no CORS and no ambient
  cross-site credential are introduced.
- Mutating forms get an intent-scoped `Idempotency-Key` automatically. The key
  survives passkey step-up and resubmission of the same browser intent.
- `phishing_resistant_auth_required` / `recent_authentication_required`
  responses surface a passkey step-up action and retry.
- Security headers: `Cache-Control: no-store`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and a
  restrictive `Content-Security-Policy` (`script-src 'self'` only).
- FastAPI's `/docs`, `/redoc` and `/openapi.json` are disabled on the console.

## Configuration

Environment variables use the `REQUEST_ENGINE_ADMIN_CONSOLE_` prefix:

```text
control_api_base_url   # e.g. http://127.0.0.1:8001
session_secret         # >= 32 bytes
session_store_directory # REQUIRED persistent private volume shared by console replicas
session_cookie_name    # default re_admin_console
setup_cookie_name      # default re_admin_setup
session_ttl_seconds    # default 1800
setup_ttl_seconds      # default 1800
cookie_secure          # default true (set false only for local http)
cookie_samesite        # lax | strict | none (default lax)
request_timeout_seconds
openapi_cache_seconds
```

WebAuthn passkeys are bound to the browser origin. The console must be served on
an origin that the control plane lists in `REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS`,
with a matching `REQUEST_ENGINE_WEBAUTHN_RP_ID`.

## Run locally (real control plane)

One command starts the **real** control plane — `platform_server:create_app`
against local PostgreSQL 18 with three least-privilege runtime logins — and the
console, both detached:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev/run_local_panel.ps1
```

Open `http://localhost:8002` (use `localhost`, not `127.0.0.1`, so the WebAuthn
RP id `localhost` is a valid secure context) and complete `/setup` -> `/login`.
While the instance is unclaimed, `/setup` drives the full first-run ceremony;
afterwards `/login` and `/operations` expose the real platform surface.

Prerequisites: the local PostgreSQL container is up and the database is migrated
to head (`alembic upgrade head`), and `uv sync` has run. The launcher provisions
the dev runtime logins from `scripts/dev/init_local_runtime_roles.sql` (throwaway
passwords, dev only), reads `built_in_native_authority_id` from
`request_engine.platform_instance`, starts the control plane on `:8001` and the
console on `:8002`, and prints readiness.

Ordering matters: the baseline role-topology guard rejects a cluster that already
contains the runtime logins, so migrate **first**, then create the logins. To
rebuild the database from the baseline, drop the `re_dev_*` logins, recreate the
database, migrate, then re-run the launcher (which re-creates the logins).

Manual equivalent:

```powershell
$env:REQUEST_ENGINE_DATABASE_URL                  = "postgresql+asyncpg://re_dev_app:dev-app-only@127.0.0.1:5432/request_engine_current"
$env:REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL    = "postgresql+asyncpg://re_dev_read:dev-read-only@127.0.0.1:5432/request_engine_current"
$env:REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL = "postgresql+asyncpg://re_dev_control:dev-control-only@127.0.0.1:5432/request_engine_current"
$env:REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID  = "<built_in_native_authority_id>"
$env:REQUEST_ENGINE_WEBAUTHN_DECOY_KEY            = "<32+ byte secret>"
$env:REQUEST_ENGINE_WEBAUTHN_RP_ID                = "localhost"
$env:REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS      = "http://localhost:8002"
uv run uvicorn request_engine.bootstrap.platform_server:create_app --factory --port 8001
```

The control plane must list the console origin in
`REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS` (here `http://localhost:8002`) and use
a matching `REQUEST_ENGINE_WEBAUTHN_RP_ID` (`localhost`), otherwise passkey
registration/login fail the origin check.

### Passkey login

`login_handle` is optional on the WebAuthn login operations. When it is omitted
the control plane runs a discoverable, usernameless ceremony (empty allow-list,
unbound challenge, identity resolved from the presented credential), so the
console signs in with a passkey and no username or password. When a handle is
supplied the original handle-first flow with the anti-enumeration decoy is
preserved. The console uses the usernameless flow; the password form remains as a
fallback.

## Resource workspaces

`/resources` groups the control plane into task-oriented workspaces. This is
deliberately **not generic CRUD**: Request Engine state changes are semantic
commands, so each workspace exposes the real read surface (list/get when the
control plane mounts one) and the real commands, running through the same owner
operation, capability, idempotency and step-up rules as the API.

- **Native identities, provisioners, identity recovery cases** — list → detail →
  actions, with the current revision pre-filled into each command's
  `expected_revision` so operators never copy concurrency preconditions by hand.
- **Platform configuration** — revisions by kind, with stage → validate →
  activate → disable and provider test.
- **Secrets and signing keyrings** — lookup by binding id (no enumeration
  operation exists), create, rotate and revoke; secret values are never echoed.
- **Deployment recovery** — inspect the active binding, configure and reconcile.
- **Organizations** — list and detail views from the platform control plane,
  plus the canonical organization-provisioning command.
- **Platform owners** and **recovery operators** — no read/list operation is
  mounted, so these pages state that explicitly and expose only the available
  commands rather than fabricating an empty table.

Staff membership operations are deliberately not projected by this console yet.
They belong to the tenant-scoped operational API (`/v1/staff`) and require an
organization actor context, while this console authenticates to the platform
control plane. Adding a second upstream and reusing the platform bearer would be
an authority-boundary bug; Staff needs an explicit tenant-selection and
tenant-authentication design before it can be added safely.

Both the workspaces and the generic `/operations` browser execute through a
single `execution.execute_operation` path, so there is no second execution path.
A `phishing_resistant_auth_required` response surfaces a passkey step-up that
retries the exact form that was submitted. Mutating actions with a
`data-confirm` prompt are confirmed before the request is issued.

## Coverage

Every operation is loaded from the control-plane OpenAPI document, so the console
projects the complete admin surface by construction; `/operations` remains the
complete, searchable escape hatch when a workspace does not exist for a given
operation. Operations under `/v1/setup` and `/auth/native` additionally have
curated first-run and login journeys.

`presentation.py` classifies discoverability only: journey, workspace/overview,
or an explicitly accepted Advanced-only operation. It never copies capability,
authority, idempotency, revision or authentication policy from OpenAPI. The
architecture coverage contract composes the real control-plane OpenAPI and fails
when an operator operation has not received an explicit admin destination, or
when a curated surface references an operation that is no longer mounted. The
runtime still falls back to Advanced so catalog drift cannot make an operation
silently unreachable while diagnostics are being performed.

## Diagnostics and error tracking

- Every request gets a correlation id (`X-Request-ID`), echoed on the response
  and in the `error.html` page.
- One structured JSON log line per request and per control-plane call is written
  to stderr (method, path, status, duration, request id). Request bodies are never
  logged, and structured fields are redacted (`password`, `token`, `secret`,
  `credential`, `cookie`, `csrf`, `recovery`, ...).
- `/diagnostics` (authenticated) shows counters, a redacted configuration summary
  and the bounded recent-error ring; `/diagnostics/errors.json` returns the same as
  JSON. With `debug=true` the error page and diagnostics include the traceback.
- Config: `log_level` (default `INFO`), `debug` (default `false`).

## UI-only mode (mock control plane)

`scripts/dev/mock_control_plane.py` is a **development-only** in-memory stand-in
for the control plane: it accepts any password/passkey and stores nothing. Use it
only to iterate on console layout without PostgreSQL/OpenBao. It is not evidence
and must never be deployed.

```powershell
uv run python scripts/dev/mock_control_plane.py   # :8001
# then start the console with
# REQUEST_ENGINE_ADMIN_CONSOLE_CONTROL_API_BASE_URL=http://127.0.0.1:8001
# Optional tenant/runtime API; required for organization staff management.
# REQUEST_ENGINE_ADMIN_CONSOLE_RUNTIME_API_BASE_URL=http://127.0.0.1:8000
```

The console keeps both upstreams separate. Platform organization reads and
creation use the control plane. The organization staff workspace uses the
runtime API and forwards `X-RE-Organization-ID` only as a tenant selector; the
runtime still resolves the bearer binding and rechecks every staff capability.
If the runtime URL is absent, the staff workspace fails closed with `503`.

The current `staff_invite` operation binds an already-provisioned native
identity. It is not an email invitation or an atomic create-and-invite workflow;
the UI labels this limitation explicitly.

## Tests

```powershell
uv run pytest tests/unit/admin_console -q
```

They cover opaque server sessions, the OpenAPI catalog and `$ref` resolution,
schema-driven form parsing, cookie/session flow, security headers, disabled
operator docs, request-id propagation, redaction, the bounded error tracker and
the diagnostics surface.
