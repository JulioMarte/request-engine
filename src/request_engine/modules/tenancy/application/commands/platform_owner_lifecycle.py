from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext


class PlatformOwnerLifecycleAction(StrEnum):
    SUSPEND = "suspend"
    REACTIVATE = "reactivate"
    REVOKE = "revoke"


_OWNER_REASONS: dict[PlatformOwnerLifecycleAction, frozenset[str]] = {
    PlatformOwnerLifecycleAction.SUSPEND: frozenset({"owner_suspension", "security_investigation"}),
    PlatformOwnerLifecycleAction.REACTIVATE: frozenset(
        {"owner_reactivation", "investigation_closed"}
    ),
    PlatformOwnerLifecycleAction.REVOKE: frozenset(
        {"owner_revocation", "credential_compromise", "owner_offboarding"}
    ),
}


class PlatformOwnerError(RuntimeError):
    pass


class PlatformOwnerForbidden(PlatformOwnerError):
    pass


class PlatformOwnerConflict(PlatformOwnerError):
    pass


class PlatformOwnerInvalid(PlatformOwnerError):
    pass


class PlatformOwnerRevisionConflict(PlatformOwnerError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionPlatformOwnerCommand:
    native_identity_id: UUID
    provenance_reference: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.provenance_reference.strip()) <= 500:
            raise ValueError("provenance_reference must contain 1 to 500 characters")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency_key must contain 1 to 200 characters")


@dataclass(frozen=True, slots=True)
class PlatformOwnerProvisioningResult:
    principal_id: UUID
    binding_id: UUID


@dataclass(frozen=True, slots=True)
class TransitionPlatformOwnerCommand:
    principal_id: UUID
    action: PlatformOwnerLifecycleAction
    expected_revision: int
    reason_code: str
    idempotency_key: str
    external_case_reference: str | None = None

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be at least 1")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency key must contain between 1 and 200 characters")
        if self.reason_code.strip() not in _OWNER_REASONS[self.action]:
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
class PlatformOwnerLifecycleResult:
    fact_id: UUID
    principal_id: UUID
    action: PlatformOwnerLifecycleAction
    authority_revision: int
    binding_id: UUID | None
    binding_status: str | None


class PlatformOwnerCommands(Protocol):
    async def provision_owner(
        self,
        actor: PlatformActorContext,
        command: ProvisionPlatformOwnerCommand,
    ) -> PlatformOwnerProvisioningResult: ...

    async def transition_owner(
        self,
        actor: PlatformActorContext,
        command: TransitionPlatformOwnerCommand,
    ) -> PlatformOwnerLifecycleResult: ...
