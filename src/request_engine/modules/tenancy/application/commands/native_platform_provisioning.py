from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext

NATIVE_INITIAL_CONTROLLER_POLICY = "tenant-controller-v2"


class NativePlatformProvisioningError(RuntimeError):
    pass


class NativePlatformProvisioningForbidden(NativePlatformProvisioningError):
    pass


class NativePlatformProvisioningConflict(NativePlatformProvisioningError):
    pass


class NativePlatformProvisioningRevisionConflict(NativePlatformProvisioningError):
    pass


class NativePlatformProvisioningInvalid(NativePlatformProvisioningError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionNativePlatformProvisionerCommand:
    identity_authority_id: UUID
    native_identity_id: UUID
    provenance_reference: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.provenance_reference.strip()) <= 500:
            raise ValueError("provenance_reference must contain 1 to 500 characters")
        if not 1 <= len(self.idempotency_key.strip()) <= 200:
            raise ValueError("idempotency_key must contain 1 to 200 characters")


@dataclass(frozen=True, slots=True)
class NativePlatformProvisionerResult:
    principal_id: UUID
    binding_id: UUID


@dataclass(frozen=True, slots=True)
class ProvisionNativeOrganizationCommand:
    organization_key: str
    display_name: str
    identity_authority_id: UUID
    native_identity_id: UUID
    provenance_reference: str
    idempotency_key: str
    initial_controller_policy: str = field(default=NATIVE_INITIAL_CONTROLLER_POLICY, init=False)

    def __post_init__(self) -> None:
        for name, limit in (
            ("organization_key", 120),
            ("display_name", 200),
            ("provenance_reference", 400),
            ("idempotency_key", 200),
        ):
            if not 1 <= len(getattr(self, name).strip()) <= limit:
                raise ValueError(f"{name} must contain 1 to {limit} characters")


@dataclass(frozen=True, slots=True)
class NativeOrganizationResult:
    organization_id: UUID
    organization_party_id: UUID
    controller_principal_id: UUID
    controller_binding_id: UUID


class NativePlatformProvisioningCommands(Protocol):
    async def provision_native_platform_provisioner(
        self, actor: PlatformActorContext, command: ProvisionNativePlatformProvisionerCommand
    ) -> NativePlatformProvisionerResult: ...

    async def provision_native_organization(
        self, actor: PlatformActorContext, command: ProvisionNativeOrganizationCommand
    ) -> NativeOrganizationResult: ...
