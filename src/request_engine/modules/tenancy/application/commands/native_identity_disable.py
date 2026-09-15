from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext

NATIVE_IDENTITY_DISABLE_CAPABILITY = "platform.identity.disable"

_DISABLE_REASONS = frozenset(
    {
        "operator_revocation",
        "credential_compromise",
        "operator_offboarding",
        "security_investigation",
    }
)


class NativeIdentityDisableError(RuntimeError):
    """Bounded governed native-identity disable failure."""


class NativeIdentityDisableForbidden(NativeIdentityDisableError):
    pass


class NativeIdentityDisableNotFound(NativeIdentityDisableError):
    pass


class NativeIdentityDisableConflict(NativeIdentityDisableError):
    pass


class NativeIdentityDisableInvalid(NativeIdentityDisableError):
    pass


class NativeIdentityDisableRevisionConflict(NativeIdentityDisableError):
    pass


@dataclass(frozen=True, slots=True)
class DisableNativeIdentityCommand:
    native_identity_id: UUID
    expected_revision: int
    reason_code: str
    idempotency_key: str
    external_case_reference: str | None = None

    def __post_init__(self) -> None:
        if self.expected_revision < 1:
            raise ValueError("expected_revision must be at least 1")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency key must contain between 1 and 200 characters")
        if self.reason_code.strip() not in _DISABLE_REASONS:
            raise ValueError("reason_code is not accepted for native identity disable")
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
class DisableNativeIdentityResult:
    fact_id: UUID
    native_identity_id: UUID
    revision_after: int
    affected_tenant_count: int
    affected_platform: bool


class NativeIdentityDisableCommands(Protocol):
    async def disable_identity(
        self,
        actor: PlatformActorContext,
        command: DisableNativeIdentityCommand,
    ) -> DisableNativeIdentityResult: ...
