from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.domain.integration_governance import IntegrationStatus
from request_engine.platform.security.context import ActorContext


@dataclass(frozen=True, slots=True)
class ProvisionIntegrationCommand:
    identity_authority_id: UUID
    credential_expires_at: datetime
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProvisionIntegrationResult:
    principal_id: UUID
    workload_identity_id: UUID
    credential_id: UUID
    binding_id: UUID
    authority_revision: int
    workload_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ReplaceIntegrationAuthorityCommand:
    integration_principal_id: UUID
    expected_authority_revision: int
    desired_capabilities: tuple[str, ...]
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TransitionIntegrationStatusCommand:
    integration_principal_id: UUID
    expected_revision: int
    target_status: IntegrationStatus
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RotateIntegrationCredentialCommand:
    integration_principal_id: UUID
    expected_revision: int
    credential_expires_at: datetime
    provenance_reference: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RotateIntegrationCredentialResult:
    credential_id: UUID
    authority_revision: int
    workload_token: str | None = field(default=None, repr=False)


class IntegrationGovernanceCommands(Protocol):
    async def rotate_integration_credential(
        self,
        actor: ActorContext,
        command: RotateIntegrationCredentialCommand,
    ) -> RotateIntegrationCredentialResult: ...

    async def provision_integration(
        self,
        actor: ActorContext,
        command: ProvisionIntegrationCommand,
    ) -> ProvisionIntegrationResult: ...

    async def replace_integration_authority(
        self,
        actor: ActorContext,
        command: ReplaceIntegrationAuthorityCommand,
    ) -> int: ...

    async def transition_integration_status(
        self,
        actor: ActorContext,
        command: TransitionIntegrationStatusCommand,
    ) -> int: ...
