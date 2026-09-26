# Deployment recovery adapters

Request Engine owns recovery **intent**. A deployment platform owns the provider-specific mechanism used to apply part of that intent. The application layer therefore depends on `DeploymentRecoveryAdapter`, not on Coolify.

The current adapter contract has three operations:

- inspect the provider's current PostgreSQL backup state;
- create a missing backup schedule;
- update an existing schedule that has drifted.

`DeploymentRecoveryReconciler` compares the active `RecoveryPolicy` with the provider state and reports `in_sync`, `drifted` or `missing`. Reconciliation is convergent: after a create/update, the adapter must re-read the external provider and Request Engine rejects the operation if the observed state still differs from desired state.

## Coolify adapter

`CoolifyRecoveryAdapter` is the first implementation. It maps the provider-neutral fields to Coolify's database backup API:

- `frequency` -> `frequency`;
- local retention days -> `database_backup_retention_days_locally`;
- off-site retention days -> `database_backup_retention_days_s3`;
- off-site required -> `save_s3` plus `s3_storage_uuid`;
- timeout -> `timeout`.

The adapter uses `GET /databases/{uuid}/backups` for observation, `POST /databases/{uuid}/backups` for creation and `PATCH /databases/{uuid}/backups/{scheduled_backup_uuid}` for drift correction. It always re-reads after a mutation instead of assuming that an HTTP success means the desired state was applied.

When more than one Coolify schedule exists, reconciliation fails closed unless the deployment target identifies the schedule UUID. It never guesses which external schedule it owns. When S3/off-site backup is required, reconciliation refuses to mutate Coolify unless an S3 storage UUID is supplied.

## Secret boundary

Provider API credentials are not fields of `RecoveryPolicy` and are not part of `DeploymentBackupTarget`. The adapter receives the credential at construction time from trusted runtime composition. Production composition must resolve that credential from the governed platform secret store. Admin/read APIs must never return it.

The current adapter implementation deliberately does not persist a Coolify token, database UUID, S3 UUID or schedule UUID by itself. Those are deployment binding concerns. A later adapter for another deployment platform can implement the same protocol without changing `DeploymentRecoveryReconciler` or the recovery policy model.

## Adding another deployment platform

A new platform implements `DeploymentRecoveryAdapter` and translates only the capabilities that platform actually supports. It must not pretend unsupported guarantees exist. If a platform cannot provide off-site retention, for example, its adapter should fail validation/reconciliation when the active policy requires it rather than silently weakening the policy.

Provider adapters should be tested with a fake transport or provider sandbox for: exact request mapping, drift detection, create/update convergence, ambiguous-resource fail-closed behavior, authentication handling, provider errors and absence of secret material from returned state.
