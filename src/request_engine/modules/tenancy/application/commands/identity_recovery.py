from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.application.queries.identity_recovery import (
    IdentityRecoveryCaseView,
)
from request_engine.platform.security.platform_context import PlatformActorContext

IDENTITY_RECOVERY_CAPABILITY = "platform.identity.recover"
IDENTITY_RECOVERY_APPROVE_CAPABILITY = "platform.identity.recovery_approve"

_CREATE_REASONS = frozenset({"operator_request", "lost_credential", "credential_compromise"})
_APPROVE_REASONS = frozenset({"ownership_verified"})
_REVOKE_REASONS = frozenset(
    {"request_withdrawn", "security_investigation", "credential_compromise"}
)


class IdentityRecoveryError(RuntimeError):
    """Bounded governed identity recovery failure."""


class IdentityRecoveryForbidden(IdentityRecoveryError):
    pass


class IdentityRecoveryNotFound(IdentityRecoveryError):
    pass


class IdentityRecoveryConflict(IdentityRecoveryError):
    pass


class IdentityRecoveryInvalid(IdentityRecoveryError):
    pass


class IdentityRecoveryRevisionConflict(IdentityRecoveryError):
    pass


class IdentityRecoveryUnavailable(IdentityRecoveryError):
    """The required technical secret-delivery boundary is unavailable."""


@dataclass(frozen=True, slots=True)
class CreateIdentityRecoveryCaseCommand:
    target_native_identity_id: UUID
    reason_code: str
    evidence_reference: str
    delivery_destination_reference: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.reason_code.strip() not in _CREATE_REASONS:
            raise IdentityRecoveryInvalid("reason_code is not accepted for a recovery request")
        if not 1 <= len(self.evidence_reference.strip()) <= 400:
            raise IdentityRecoveryInvalid(
                "evidence reference must contain between 1 and 400 characters"
            )
        if not 1 <= len(self.delivery_destination_reference.strip()) <= 200:
            raise IdentityRecoveryInvalid(
                "delivery destination must contain between 1 and 200 characters"
            )
        _validate_idempotency_key(self.idempotency_key)

    @property
    def normalized_reason_code(self) -> str:
        return self.reason_code.strip()

    @property
    def normalized_evidence_reference(self) -> str:
        return self.evidence_reference.strip()

    @property
    def normalized_destination_reference(self) -> str:
        return self.delivery_destination_reference.strip()


@dataclass(frozen=True, slots=True)
class ApproveIdentityRecoveryCaseCommand:
    case_id: UUID
    expected_revision: int
    reason_code: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise IdentityRecoveryInvalid("expected_revision must be at least 1")
        if self.reason_code.strip() not in _APPROVE_REASONS:
            raise IdentityRecoveryInvalid("reason_code is not accepted for a recovery approval")
        _validate_idempotency_key(self.idempotency_key)

    @property
    def normalized_reason_code(self) -> str:
        return self.reason_code.strip()


@dataclass(frozen=True, slots=True)
class IssueIdentityRecoveryCaseCommand:
    case_id: UUID
    expected_revision: int
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise IdentityRecoveryInvalid("expected_revision must be at least 1")
        _validate_idempotency_key(self.idempotency_key)


@dataclass(frozen=True, slots=True)
class RevokeIdentityRecoveryCaseCommand:
    case_id: UUID
    expected_revision: int
    reason_code: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise IdentityRecoveryInvalid("expected_revision must be at least 1")
        if self.reason_code.strip() not in _REVOKE_REASONS:
            raise IdentityRecoveryInvalid("reason_code is not accepted for a recovery revocation")
        _validate_idempotency_key(self.idempotency_key)

    @property
    def normalized_reason_code(self) -> str:
        return self.reason_code.strip()


class IdentityRecoveryCommands(Protocol):
    async def create_case(
        self,
        actor: PlatformActorContext,
        command: CreateIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView: ...

    async def approve_case(
        self,
        actor: PlatformActorContext,
        command: ApproveIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView: ...

    async def issue_case(
        self,
        actor: PlatformActorContext,
        command: IssueIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView: ...

    async def revoke_case(
        self,
        actor: PlatformActorContext,
        command: RevokeIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView: ...


def _validate_idempotency_key(value: str) -> None:
    if not 1 <= len(value.strip()) <= 200:
        raise IdentityRecoveryInvalid("idempotency key must contain between 1 and 200 characters")
