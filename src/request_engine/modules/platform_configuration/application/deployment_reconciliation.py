from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from request_engine.modules.platform_configuration.application.recovery_policy import (
    RecoveryPolicy,
)


class DeploymentReconciliationState(StrEnum):
    IN_SYNC = "in_sync"
    DRIFTED = "drifted"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class DeploymentBackupTarget:
    resource_id: str
    schedule_id: str | None = None
    offsite_storage_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeploymentBackupState:
    schedule_id: str | None
    frequency: str | None
    local_retention_days: int | None
    offsite_retention_days: int | None
    timeout_seconds: int | None
    offsite_enabled: bool | None


@dataclass(frozen=True, slots=True)
class DeploymentReconciliationPlan:
    state: DeploymentReconciliationState
    desired: DeploymentBackupState
    actual: DeploymentBackupState | None
    changes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeploymentReconciliationResult:
    provider_kind: str
    state: DeploymentReconciliationState
    schedule_id: str | None
    changed: bool
    changes: tuple[str, ...]


class DeploymentRecoveryAdapter(Protocol):
    @property
    def provider_kind(self) -> str: ...

    async def inspect_backup(
        self,
        target: DeploymentBackupTarget,
    ) -> DeploymentBackupState | None: ...

    async def create_backup(
        self,
        target: DeploymentBackupTarget,
        desired: DeploymentBackupState,
    ) -> DeploymentBackupState: ...

    async def update_backup(
        self,
        target: DeploymentBackupTarget,
        desired: DeploymentBackupState,
    ) -> DeploymentBackupState: ...


class DeploymentRecoveryReconciler:
    def __init__(self, adapter: DeploymentRecoveryAdapter) -> None:
        self._adapter = adapter

    async def plan(
        self,
        *,
        policy: RecoveryPolicy,
        target: DeploymentBackupTarget,
    ) -> DeploymentReconciliationPlan:
        desired = _desired_state(policy, target)
        actual = await self._adapter.inspect_backup(target)
        if actual is None:
            return DeploymentReconciliationPlan(
                state=DeploymentReconciliationState.MISSING,
                desired=desired,
                actual=None,
                changes=("create_schedule",),
            )
        changes = _changes(desired, actual)
        return DeploymentReconciliationPlan(
            state=(
                DeploymentReconciliationState.IN_SYNC
                if not changes
                else DeploymentReconciliationState.DRIFTED
            ),
            desired=desired,
            actual=actual,
            changes=changes,
        )

    async def reconcile(
        self,
        *,
        policy: RecoveryPolicy,
        target: DeploymentBackupTarget,
    ) -> DeploymentReconciliationResult:
        plan = await self.plan(policy=policy, target=target)
        if plan.state is DeploymentReconciliationState.IN_SYNC:
            return DeploymentReconciliationResult(
                provider_kind=self._adapter.provider_kind,
                state=plan.state,
                schedule_id=plan.actual.schedule_id if plan.actual is not None else None,
                changed=False,
                changes=(),
            )
        if plan.state is DeploymentReconciliationState.MISSING:
            applied = await self._adapter.create_backup(target, plan.desired)
        else:
            applied = await self._adapter.update_backup(target, plan.desired)
        remaining = _changes(plan.desired, applied)
        if remaining:
            raise RuntimeError("deployment provider did not converge to requested recovery policy")
        return DeploymentReconciliationResult(
            provider_kind=self._adapter.provider_kind,
            state=DeploymentReconciliationState.IN_SYNC,
            schedule_id=applied.schedule_id,
            changed=True,
            changes=plan.changes,
        )


def _desired_state(
    policy: RecoveryPolicy,
    target: DeploymentBackupTarget,
) -> DeploymentBackupState:
    return DeploymentBackupState(
        schedule_id=target.schedule_id,
        frequency=policy.postgres.frequency,
        local_retention_days=policy.postgres.local_retention_days,
        offsite_retention_days=policy.postgres.s3_retention_days,
        timeout_seconds=policy.postgres.timeout_seconds,
        offsite_enabled=policy.postgres.require_s3,
    )


def _changes(
    desired: DeploymentBackupState,
    actual: DeploymentBackupState,
) -> tuple[str, ...]:
    fields = (
        "frequency",
        "local_retention_days",
        "offsite_retention_days",
        "timeout_seconds",
        "offsite_enabled",
    )
    return tuple(field for field in fields if getattr(desired, field) != getattr(actual, field))
