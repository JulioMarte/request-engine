# Deployment recovery adapters

Request Engine owns recovery **intent**. A deployment platform owns the provider-specific mechanism used to apply part of that intent. The application layer therefore depends on `DeploymentRecoveryAdapter`, not on Coolify.

The adapter contract has three operations: inspect current PostgreSQL backup state, create a missing schedule, and update an existing schedule that has drifted. `DeploymentRecoveryReconciler` reports `in_sync`, `drifted` or `missing`. Reconciliation is convergent: after mutation the provider is re-read and a false convergence is rejected.

## Governed deployment binding

Provider coordinates are persisted separately from `RecoveryPolicy` as the active `operations.deployment_recovery` configuration. The first provider is `coolify` and its payload contains only non-secret coordinates:

- `base_url`;
- `database_uuid`;
- `scheduled_backup_uuid` (optional when discovery is unambiguous);
- `s3_storage_uuid` (optional unless the recovery policy requires off-site backup).

The configuration carries a normal `secret_binding_id`. The referenced governed secret must have purpose `deployment.coolify.api_token`; its value lives in OpenBao and is resolved only inside the control plane immediately before provider access. The token is never stored in the configuration JSON and never returned by read, plan or reconciliation responses.

The admin workflow is:

1. `POST /v1/platform/secrets` with purpose `deployment.coolify.api_token` and the token value. This is the existing step-up-protected OpenBao secret surface.
2. `PUT /v1/platform/deployment-recovery` with the returned `secret_binding_id` and provider coordinates. The control plane stages, validates the exact secret binding/backend versions, and activates the deployment binding using the existing revision and idempotency machinery.
3. `GET /v1/platform/deployment-recovery:plan` reads provider state and returns drift without mutation.
4. `POST /v1/platform/deployment-recovery:reconcile` requires phishing-resistant step-up, resolves the token server-side, applies the minimum required provider mutation and verifies convergence.

This deliberately keeps `RecoveryPolicy` portable. A Kubernetes, Dokploy, Nomad or other adapter can define its own deployment-binding coordinates while preserving the same policy and reconciler.

## Coolify adapter

`CoolifyRecoveryAdapter` maps provider-neutral fields to Coolify's database backup API: `frequency`, local and S3 retention days, `save_s3`/`s3_storage_uuid`, and timeout. It uses `GET /databases/{uuid}/backups`, `POST /databases/{uuid}/backups`, and `PATCH /databases/{uuid}/backups/{scheduled_backup_uuid}`.

When more than one Coolify schedule exists, reconciliation fails closed unless the binding identifies the schedule UUID. It never guesses. When off-site backup is required, mutation is rejected unless an S3 storage UUID exists. The adapter also refuses to send an API token over plain HTTP.

## Contract testing against Coolify

Unit tests use `httpx.MockTransport` to assert exact request bodies, authentication, drift behavior and post-mutation convergence. In addition, `.github/workflows/coolify-adapter-contract.yml` pulls the pinned upstream `ghcr.io/coollabsio/coolify:4.3.23` image and asks that image's Laravel router for its API route table. CI fails if the GET/POST/PATCH scheduled-database-backup routes required by the adapter disappear. This is intentionally pinned: an upstream `latest` change must not silently redefine the provider contract.

This image test proves the API surface exists in the exact Coolify release we claim to support; it is not a substitute for a full installed Coolify server with PostgreSQL, Redis, Docker socket, SSH host and a real managed database. A live-environment acceptance test remains the final deployment proof because Coolify itself is a multi-service control plane rather than a hermetic single-container API fixture.

## Adding another deployment platform

A new platform implements `DeploymentRecoveryAdapter` and translates only capabilities it really supports. Unsupported guarantees must fail validation/reconciliation rather than silently weaken the active policy. Provider adapters should cover exact mapping, drift detection, convergence, ambiguous-resource fail-closed behavior, authentication/provider errors and absence of secret material from returned state.
