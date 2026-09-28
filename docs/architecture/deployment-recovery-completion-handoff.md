# Deployment recovery completion handoff

## Purpose

This handoff records the verified state of the governed Coolify deployment binding work on `feature/platform-config-openbao-recovery`, what the pinned-image contract test proves, and what still has to be demonstrated before calling the feature production-complete.

## Current branch state

Verified branch head at handoff start: `ba55b2a86a4edac980bb78ebc9276aabe024b43e`.

The implementation now contains all of the main server-side pieces requested for a governed deployment binding:

- `operations.deployment_recovery` is a configuration separate from `operations.recovery_policy`.
- The binding contains Coolify coordinates (`base_url`, `database_uuid`, optional `scheduled_backup_uuid`, optional `s3_storage_uuid`) plus a governed `secret_binding_id`.
- The Coolify API token is created through the existing platform secret administration surface and stored through the configured `PlatformSecretStore`/OpenBao path. It is not embedded in deployment configuration JSON.
- `DeploymentRecoveryService` resolves the secret binding and then the secret value only inside the server immediately before provider access.
- `GET /v1/platform/deployment-recovery:plan` inspects drift without mutation.
- `POST /v1/platform/deployment-recovery:reconcile` performs reconciliation and is protected by the platform configuration mutation capability plus phishing-resistant step-up.
- `PUT /v1/platform/deployment-recovery` stages, validates and activates the governed binding.
- `create_platform_control_app()` installs the deployment recovery HTTP surface and passes the platform secret store into it.

Primary implementation sources:

- `src/request_engine/modules/platform_configuration/application/deployment_binding.py`
- `src/request_engine/modules/platform_configuration/application/deployment_reconciliation.py`
- `src/request_engine/modules/platform_configuration/adapters/coolify_recovery.py`
- `src/request_engine/modules/platform_configuration/api/deployment_http.py`
- `src/request_engine/modules/platform_configuration/api/http.py`
- `src/request_engine/entrypoints/http/platform_control_app.py`
- `src/request_engine/bootstrap/platform_server.py`
- `src/request_engine/bootstrap/platform_secrets.py`

Architecture/contract source:

- `docs/architecture/deployment-recovery-adapters.md`

Tests:

- `tests/modules/platform_configuration/test_deployment_binding.py`
- `tests/modules/platform_configuration/test_deployment_reconciliation.py`
- `tests/modules/platform_configuration/test_coolify_recovery_adapter.py`
- `.github/workflows/coolify-adapter-contract.yml`
- `scripts/ci/check_coolify_backup_routes.py`

## What the Coolify image test proves

The dedicated workflow pins `ghcr.io/coollabsio/coolify:4.3.23`, copies `/var/www/html/routes/api.php` from the real upstream image, verifies that the GET/POST/PATCH scheduled database-backup routes expected by the adapter still exist, and then runs the adapter/reconciler/binding tests.

This is valuable contract evidence. It protects us from silently claiming compatibility with a Coolify release whose route surface has changed.

It does **not** prove that Request Engine can perform a real authenticated backup reconciliation against a running Coolify installation. The Coolify image is a component of a multi-service control plane and the workflow does not boot a complete Coolify installation with its database, Redis, Docker/SSH environment, managed PostgreSQL resource, storage target and real API token.

Therefore the pinned-image contract test is necessary, but it is not the final production acceptance test.

## CI state observed before this handoff

A previous PR integration run for source head `fdc934779e97222fd4e719d30ecddd81f3e2600c` failed `Python quality and architecture` only because Ruff found formatting/import-order/line-length problems in the newly added deployment binding files. Those formatting defects were subsequently fixed on the branch.

The later branch head observed for this handoff is `ba55b2a86a4edac980bb78ebc9276aabe024b43e`. At the time this handoff was written, the new head did not yet have a completed PR-triggered workflow run returned by the workflow query. Do not claim exact-head CI green until GitHub Actions has actually completed for the current head (or its successor containing this handoff).

## Remaining work before production-complete

### 1. Obtain exact-head CI evidence

Wait for/run CI on the final commit and require all mandatory checks to be green. In particular confirm Python quality, architecture/policy checks, DB/integration suites, and the dedicated `Coolify adapter contract` workflow. Do not reuse green evidence from an older SHA.

### 2. Add/verify HTTP integration coverage for the new administrative journey

The service-level tests prove server-side secret resolution and reconciliation behavior, but the final journey should exercise the actual platform-control HTTP composition:

1. authenticate as a platform owner with phishing-resistant assurance;
2. create a secret with purpose `deployment.coolify.api_token` through `POST /v1/platform/secrets`;
3. configure the deployment binding with `PUT /v1/platform/deployment-recovery`;
4. verify no token appears in configuration/read/plan responses;
5. call `GET /v1/platform/deployment-recovery:plan`;
6. call `POST /v1/platform/deployment-recovery:reconcile`;
7. verify authorization/step-up failures for insufficient assurance;
8. verify revoked/wrong-purpose/missing/unavailable OpenBao secret cases fail closed.

Prefer a DB-backed integration/E2E test using the real Postgres configuration/secret-binding functions instead of mocks for this layer.

### 3. Perform a live Coolify acceptance test

Provision an isolated disposable Coolify environment using the same supported release (`4.3.23`) and a disposable PostgreSQL resource. Create a scoped Coolify API token, store it through Request Engine's OpenBao-backed admin secret flow, create the governed deployment binding, intentionally create drift in the backup schedule, then prove:

- plan reports the real drift;
- reconcile changes only the expected fields;
- a second plan reports `in_sync`;
- the configured S3 target is used when off-site backup is required;
- ambiguous schedule discovery fails closed;
- invalid/revoked Coolify credentials fail without leaking the token;
- Request Engine responses/logs/audit material do not contain the token.

This acceptance environment should be disposable and must not use production credentials.

### 4. Verify admin-panel UX, if the UI is part of the requested Definition of Done

The backend now exposes the primitives required by a panel, but this repository evidence does not establish that a browser admin UI exists with the originally proposed Recovery Policy / Deployment / Reconciliation presentation.

If the product has a separate admin frontend, wire it to the existing governed-secret flow rather than adding a plaintext token field to deployment configuration. The UI may accept the token only as a write-only secret-creation input; after submission it should retain/display only secret-binding metadata, never the token value.

Expected panel behavior:

- token input is write-only and cannot be read back;
- provider coordinates are editable independently of Recovery Policy;
- plan shows `in_sync`, `drifted` or `missing` and the changed fields;
- reconcile requires fresh phishing-resistant authentication;
- errors distinguish bad provider configuration, unavailable secret backend and provider failure without exposing secret material.

### 5. Close documentation/evidence only after the above proof

Update `docs/architecture/deployment-recovery-adapters.md` with the live acceptance procedure/result and exact tested Coolify version. If a dedicated operational runbook exists, link the procedure there as well. Record exact commit SHA and CI run used as completion evidence.

## Completion rule

Do not mark this feature fully complete merely because the pinned Coolify image contract test is green.

It can be considered implementation-complete when exact-head CI and the DB-backed HTTP administrative journey are green. It can be considered production-accepted only after a disposable real Coolify installation proves authenticated plan -> reconcile -> convergence using a token stored/resolved through the OpenBao-backed governed secret path, with no secret leakage.

If the original scope explicitly includes a graphical admin panel, production completion also requires that UI integration; the current repository evidence proves the backend administrative API, not the browser panel.

## Recommended next-agent order

1. Re-read `docs/architecture/deployment-recovery-adapters.md` and this handoff.
2. Check the current branch HEAD and exact-head GitHub Actions status before editing anything.
3. Add the DB-backed platform-control HTTP integration test for secret -> binding -> plan -> reconcile and negative cases.
4. Fix any failures without weakening capability, step-up, secret-binding or fail-closed semantics.
5. Bring exact-head CI to green.
6. Run the disposable full Coolify acceptance test and record evidence.
7. If a separate admin frontend exists, finish the write-only token/binding/reconciliation UX there.
8. Update docs with exact SHA, CI run and live acceptance result, then hand off/merge according to repository policy.
