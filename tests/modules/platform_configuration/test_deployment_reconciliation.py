from __future__ import annotations

import pytest

from request_engine.modules.platform_configuration.application.deployment_reconciliation import (
    DeploymentBackupState,
    DeploymentBackupTarget,
    DeploymentReconciliationState,
    DeploymentRecoveryReconciler,
)
from request_engine.modules.platform_configuration.application.recovery_policy import (
    recovery_policy_preset,
)


class _Adapter:
    provider_kind = "fake"

    def __init__(self, actual: DeploymentBackupState | None) -> None:
        self.actual = actual
        self.created = False
        self.updated = False

    async def inspect_backup(self, target: DeploymentBackupTarget) -> DeploymentBackupState | None:
        del target
        return self.actual

    async def create_backup(
        self, target: DeploymentBackupTarget, desired: DeploymentBackupState
    ) -> DeploymentBackupState:
        del target
        self.created = True
        self.actual = DeploymentBackupState(
            "created",
            desired.frequency,
            desired.local_retention_days,
            desired.offsite_retention_days,
            desired.timeout_seconds,
            desired.offsite_enabled,
        )
        return self.actual

    async def update_backup(
        self, target: DeploymentBackupTarget, desired: DeploymentBackupState
    ) -> DeploymentBackupState:
        del target
        self.updated = True
        self.actual = DeploymentBackupState(
            "existing",
            desired.frequency,
            desired.local_retention_days,
            desired.offsite_retention_days,
            desired.timeout_seconds,
            desired.offsite_enabled,
        )
        return self.actual


@pytest.mark.asyncio
async def test_plan_reports_in_sync_without_mutation() -> None:
    adapter = _Adapter(DeploymentBackupState("existing", "hourly", 7, 30, 3600, True))
    reconciler = DeploymentRecoveryReconciler(adapter)
    plan = await reconciler.plan(
        policy=recovery_policy_preset(),
        target=DeploymentBackupTarget("db", "existing", "s3"),
    )
    assert plan.state is DeploymentReconciliationState.IN_SYNC
    assert plan.changes == ()
    assert adapter.created is False
    assert adapter.updated is False


@pytest.mark.asyncio
async def test_plan_reports_precise_drift() -> None:
    reconciler = DeploymentRecoveryReconciler(
        _Adapter(DeploymentBackupState("existing", "daily", 3, 30, 3600, True))
    )
    plan = await reconciler.plan(
        policy=recovery_policy_preset(),
        target=DeploymentBackupTarget("db", "existing", "s3"),
    )
    assert plan.state is DeploymentReconciliationState.DRIFTED
    assert plan.changes == ("frequency", "local_retention_days")


@pytest.mark.asyncio
async def test_reconcile_creates_missing_schedule() -> None:
    adapter = _Adapter(None)
    result = await DeploymentRecoveryReconciler(adapter).reconcile(
        policy=recovery_policy_preset(),
        target=DeploymentBackupTarget("db", offsite_storage_id="s3"),
    )
    assert result.state is DeploymentReconciliationState.IN_SYNC
    assert result.schedule_id == "created"
    assert result.changed is True
    assert result.changes == ("create_schedule",)
    assert adapter.created is True


@pytest.mark.asyncio
async def test_reconcile_updates_drifted_schedule() -> None:
    adapter = _Adapter(DeploymentBackupState("existing", "daily", 7, 30, 3600, True))
    result = await DeploymentRecoveryReconciler(adapter).reconcile(
        policy=recovery_policy_preset(),
        target=DeploymentBackupTarget("db", "existing", "s3"),
    )
    assert result.state is DeploymentReconciliationState.IN_SYNC
    assert result.changed is True
    assert result.changes == ("frequency",)
    assert adapter.updated is True
