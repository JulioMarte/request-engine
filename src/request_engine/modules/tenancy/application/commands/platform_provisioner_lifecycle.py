from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext


class PlatformProvisionerLifecycleAction(StrEnum):
    SUSPEND = "suspend"
    REACTIVATE = "reactivate"
    REVOKE = "revoke"


_LIFECYCLE_REASONS: dict[PlatformProvisionerLifecycleAction, frozenset[str]] = {
    PlatformProvisionerLifecycleAction.SUSPEND: frozenset(
        {"operator_suspension", "security_investigation"}
    ),
    PlatformProvisionerLifecycleAction.REACTIVATE: frozenset(
        {"operator_reactivation", "investigation_closed"}
    ),
    PlatformProvisionerLifecycleAction.REVOKE: frozenset(
        {"operator_revocation", "credential_compromise", "operator_offboarding"}
    ),
}


class PlatformProvisionerLifecycleError(RuntimeError):
    """Bounded platform provisioner lifecycle failure."""


class PlatformProvisionerLifecycleForbidden(PlatformProvisionerLifecycleError):
    pass


class PlatformProvisionerLifecycleNotFound(PlatformProvisionerLifecycleError):
    pass


class PlatformProvisionerLifecycleConflict(PlatformProvisionerLifecycleError):
    pass


class PlatformProvisionerLifecycleInvalid(PlatformProvisionerLifecycleError):
    pass


class PlatformProvisionerLifecycleRevisionConflict(PlatformProvisionerLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class TransitionPlatformProvisionerCommand:
    principal_id: UUID
    action: PlatformProvisionerLifecycleAction
    expected_revision: int
    reason_code: str
    idempotency_key: str
    external_case_reference: str | None = None

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be at least 1")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency key must contain between 1 and 200 characters")
        if self.reason_code.strip() not in _LIFECYCLE_REASONS[self.action]:
            raise ValueError("reason_code is not accepted for the requested lifecycle action")
        if self.external_case_reference is not None and not (
            1 <= len(self.external_case_reference.strip()) <= 200
        ):
            raise ValueError("external case reference must contain between 1 and 200 characters")

    @property
    def normalized_reason_code(self) -> str:
        return self.reason_code.strip()

    @property
    def normalized_case_reference(self) -> str | None:
        if self.external_case_reference is None:
            return None
        return self.external_case_reference.strip()


@dataclass(frozen=True, slots=True)
class PlatformProvisionerLifecycleResult:
    fact_id: UUID
    principal_id: UUID
    action: PlatformProvisionerLifecycleAction
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None


class PlatformProvisionerLifecycleCommands(Protocol):
    async def transition_provisioner(
        self,
        actor: PlatformActorContext,
        command: TransitionPlatformProvisionerCommand,
    ) -> PlatformProvisionerLifecycleResult: ...
