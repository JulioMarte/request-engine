from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationRevision,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
)
from request_engine.modules.platform_configuration.application.deployment_reconciliation import (
    DeploymentReconciliationPlan,
    DeploymentReconciliationResult,
    DeploymentRecoveryAdapter,
    DeploymentRecoveryReconciler,
    DeploymentBackupTarget,
)
from request_engine.modules.platform_configuration.application.provider_secrets import (
    ProviderSecretResolver,
)
from request_engine.modules.platform_configuration.application.recovery_policy import (
    RecoveryPolicy,
    parse_recovery_policy,
    recovery_policy_preset,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)
from request_engine.platform.security.platform_context import PlatformActorContext

DEPLOYMENT_BINDING_KIND: Final = "operations.deployment_recovery"
DEPLOYMENT_BINDING_PROVIDER: Final = "coolify"
DEPLOYMENT_TOKEN_PURPOSE: Final = "deployment.coolify.api_token"


@dataclass(frozen=True, slots=True)
class DeploymentBinding:
    provider_kind: str
    base_url: str
    database_uuid: str
    scheduled_backup_uuid: str | None
    s3_storage_uuid: str | None
    secret_binding_id: UUID
    revision: int

    @property
    def target(self) -> DeploymentBackupTarget:
        return DeploymentBackupTarget(
            resource_id=self.database_uuid,
            schedule_id=self.scheduled_backup_uuid,
            offsite_storage_id=self.s3_storage_uuid,
        )


def parse_deployment_binding(revision: ConfigurationRevision) -> DeploymentBinding:
    if revision.configuration_kind != DEPLOYMENT_BINDING_KIND:
        raise PlatformConfigurationInvalid()
    if revision.provider_kind != DEPLOYMENT_BINDING_PROVIDER or revision.secret_binding_id is None:
        raise PlatformConfigurationInvalid()
    payload = revision.configuration
    if set(payload) != {"base_url", "database_uuid", "scheduled_backup_uuid", "s3_storage_uuid"}:
        raise PlatformConfigurationInvalid()

    def required(name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise PlatformConfigurationInvalid()
        return value.strip()

    def optional(name: str) -> str | None:
        value = payload.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise PlatformConfigurationInvalid()
        return value.strip()

    base_url = required("base_url")
    if not base_url.startswith("https://"):
        raise PlatformConfigurationInvalid()
    return DeploymentBinding(
        provider_kind=revision.provider_kind,
        base_url=base_url,
        database_uuid=required("database_uuid"),
        scheduled_backup_uuid=optional("scheduled_backup_uuid"),
        s3_storage_uuid=optional("s3_storage_uuid"),
        secret_binding_id=revision.secret_binding_id,
        revision=revision.revision,
    )


class DeploymentBindingReader:
    async def list_revisions(
        self, actor: PlatformActorContext, configuration_kind: str | None = None
    ) -> list[ConfigurationRevision]: ...


class DeploymentRecoveryService:
    def __init__(
        self,
        *,
        reader: DeploymentBindingReader,
        secret_resolver: ProviderSecretResolver,
        secret_store: PlatformSecretStore | None,
        adapter_factory: callable,
    ) -> None:
        self._reader = reader
        self._secret_resolver = secret_resolver
        self._secret_store = secret_store
        self._adapter_factory = adapter_factory

    async def plan(self, actor: PlatformActorContext) -> tuple[DeploymentBinding, DeploymentReconciliationPlan]:
        binding, policy, adapter = await self._runtime(actor, capability_key="platform.deployment.read")
        return binding, await DeploymentRecoveryReconciler(adapter).plan(policy=policy, target=binding.target)

    async def reconcile(
        self, actor: PlatformActorContext
    ) -> tuple[DeploymentBinding, DeploymentReconciliationResult]:
        binding, policy, adapter = await self._runtime(
            actor, capability_key="platform.deployment.reconcile"
        )
        return binding, await DeploymentRecoveryReconciler(adapter).reconcile(
            policy=policy, target=binding.target
        )

    async def _runtime(
        self, actor: PlatformActorContext, *, capability_key: str
    ) -> tuple[DeploymentBinding, RecoveryPolicy, DeploymentRecoveryAdapter]:
        rows = await self._reader.list_revisions(actor, DEPLOYMENT_BINDING_KIND)
        active = next((row for row in rows if row.state == "active"), None)
        if active is None:
            raise PlatformConfigurationNotFound()
        binding = parse_deployment_binding(active)
        reference = await self._secret_resolver.resolve(
            actor, binding_id=binding.secret_binding_id, capability_key=capability_key
        )
        if reference.purpose != DEPLOYMENT_TOKEN_PURPOSE or reference.status != "active":
            raise PlatformConfigurationInvalid()
        if self._secret_store is None:
            raise PlatformSecretStoreUnavailable()
        try:
            token = await self._secret_store.resolve(secret_id=reference.secret_id)
        except PlatformSecretNotFound:
            raise PlatformConfigurationInvalid() from None

        policy_rows = await self._reader.list_revisions(actor, "operations.recovery_policy")
        active_policy = next((row for row in policy_rows if row.state == "active"), None)
        policy = recovery_policy_preset() if active_policy is None else parse_recovery_policy(active_policy.configuration)
        adapter = self._adapter_factory(binding, token)
        return binding, policy, adapter
