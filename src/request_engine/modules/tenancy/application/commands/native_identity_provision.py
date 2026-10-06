from dataclasses import dataclass, field
from uuid import UUID


class NativeIdentityProvisionError(RuntimeError):
    pass


class NativeIdentityProvisionConflict(NativeIdentityProvisionError):
    pass


class NativeIdentityProvisionForbidden(NativeIdentityProvisionError):
    pass


class NativeIdentityProvisionInvalid(NativeIdentityProvisionError):
    pass


class NativeIdentityProvisionUnavailable(NativeIdentityProvisionError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionNativeIdentityCommand:
    login_handle: str
    password: str = field(repr=False)
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 250:
            raise NativeIdentityProvisionInvalid()


@dataclass(frozen=True, slots=True)
class NativeIdentityProvisionResult:
    native_identity_id: UUID
    login_handle: str
