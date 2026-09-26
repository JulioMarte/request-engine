from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationRevision,
    PlatformConfigurationInvalid,
)
from request_engine.modules.platform_configuration.application.deployment_binding import (
    DEPLOYMENT_BINDING_KIND,
    DEPLOYMENT_TOKEN_PURPOSE,
    DeploymentBinding,
    DeploymentRecoveryService,
    parse_deployment_binding,
)
from request_engine.modules.platform_configuration.application.deployment_reconciliation import (
    DeploymentBackupState,
    DeploymentBackupTarget,
)
from request_engine.modules.platform_configuration.application.provider_secrets import ProviderSecretReference

ACTOR_ID = UUID("00000000-0000-0000-0000-000000000001")
BINDING_ID = UUID("00000000-0000-0000-0000-000000000002")
SECRET_ID = UUID("00000000-0000-0000-0000-000000000003")


def _revision(*, secret_binding_id: UUID | None = BINDING_ID) -> ConfigurationRevision:
    return ConfigurationRevision(
        configuration_revision_id=uuid4(),
        configuration_kind=DEPLOYMENT_BINDING_KIND,
        provider_kind="coolify",
        revision=3,
        configuration={
            "base_url": "https://coolify.example/api/v1",
            "database_uuid": "db-1",
            "scheduled_backup_uuid": "backup-1",
            "s3_storage_uuid": "s3-1",
        },
        secret_binding_id=secret_binding_id,
        state="active",
        created_by_principal_id=ACTOR_ID,
        created_at=datetime.now(UTC),
        validated_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
        disabled_at=None,
    )


def test_binding_parser_keeps_provider_coordinates_out_of_recovery_policy() -> None:
    binding = parse_deployment_binding(_revision())
    assert binding == DeploymentBinding(
        "coolify",
        "https://coolify.example/api/v1",
        "db-1",
        "backup-1",
        "s3-1",
        BINDING_ID,
        3,
    )
    assert binding.target == DeploymentBackupTarget("db-1", "backup-1", "s3-1")


def test_binding_parser_rejects_plain_http_and_missing_secret_binding() -> None:
    row = _revision()
    bad = ConfigurationRevision(
        configuration_revision_id=row.configuration_revision_id,
        configuration_kind=row.configuration_kind,
        provider_kind=row.provider_kind,
        revision=row.revision,
        configuration={**row.configuration, "base_url": "http://coolify.example/api/v1"},
        secret_binding_id=row.secret_binding_id,
        state=row.state,
        created_by_principal_id=row.created_by_principal_id,
        created_at=row.created_at,
        validated_at=row.validated_at,
        activated_at=row.activated_at,
        disabled_at=row.disabled_at,
    )
    with pytest.raises(PlatformConfigurationInvalid):
        parse_deployment_binding(bad)
    with pytest.raises(PlatformConfigurationInvalid):
        parse_deployment_binding(_revision(secret_binding_id=None))


@dataclass
class FakeReader:
    binding: ConfigurationRevision

    async def list_revisions(self, actor: object, configuration_kind: str | None = None):
        del actor
        if configuration_kind == DEPLOYMENT_BINDING_KIND:
            return [self.binding]
        if configuration_kind == "operations.recovery_policy":
            return []
        return []


class FakeResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    async def resolve(self, actor: object, *, binding_id: UUID, capability_key: str):
        del actor
        self.calls.append((binding_id, capability_key))
        return ProviderSecretReference(
            binding_id=binding_id,
            secret_id=SECRET_ID,
            purpose=DEPLOYMENT_TOKEN_PURPOSE,
            backend="openbao",
            backend_version=4,
            status="active",
            revision=2,
        )


class FakeStore:
    async def resolve(self, *, secret_id: UUID) -> str:
        assert secret_id == SECRET_ID
        return "token-from-openbao"

    async def put(self, **kwargs: object):
        raise AssertionError("not used")

    async def delete(self, **kwargs: object):
        raise AssertionError("not used")


class FakeAdapter:
    provider_kind = "coolify"

    async def inspect_backup(self, target: DeploymentBackupTarget):
        assert target == DeploymentBackupTarget("db-1", "backup-1", "s3-1")
        return DeploymentBackupState("backup-1", "daily", 3, 30, 3600, True)

    async def create_backup(self, target: DeploymentBackupTarget, desired: DeploymentBackupState):
        raise AssertionError("existing schedule must not be created")

    async def update_backup(self, target: DeploymentBackupTarget, desired: DeploymentBackupState):
        return DeploymentBackupState("backup-1", "hourly", 7, 30, 3600, True)


@pytest.mark.asyncio
async def test_service_resolves_token_only_server_side_and_reports_drift() -> None:
    resolver = FakeResolver()
    captured: list[tuple[DeploymentBinding, str]] = []

    def factory(binding: DeploymentBinding, token: str):
        captured.append((binding, token))
        return FakeAdapter()

    service = DeploymentRecoveryService(
        reader=FakeReader(_revision()),
        secret_resolver=resolver,  # type: ignore[arg-type]
        secret_store=FakeStore(),  # type: ignore[arg-type]
        adapter_factory=factory,
    )
    binding, plan = await service.plan(object())  # type: ignore[arg-type]
    assert binding.database_uuid == "db-1"
    assert plan.status == "drifted"
    assert {change.field for change in plan.changes} == {"frequency", "local_retention_days"}
    assert captured[0][1] == "token-from-openbao"
    assert resolver.calls == [(BINDING_ID, "platform.configuration.read")]
    assert "token-from-openbao" not in repr(binding)
    assert "token-from-openbao" not in repr(plan)


@pytest.mark.asyncio
async def test_reconcile_uses_mutation_capability_and_verifies_convergence() -> None:
    resolver = FakeResolver()
    service = DeploymentRecoveryService(
        reader=FakeReader(_revision()),
        secret_resolver=resolver,  # type: ignore[arg-type]
        secret_store=FakeStore(),  # type: ignore[arg-type]
        adapter_factory=lambda binding, token: FakeAdapter(),
    )
    _, result = await service.reconcile(object())  # type: ignore[arg-type]
    assert result.before.status == "drifted"
    assert result.after.status == "in_sync"
    assert result.action == "updated"
    assert resolver.calls == [(BINDING_ID, "platform.configuration.activate")]
