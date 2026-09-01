from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from request_engine.platform.security.capabilities import grant_satisfies


class PrincipalKind(StrEnum):
    HUMAN = "human"
    INTEGRATION = "integration"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Trusted execution identity produced by an authentication adapter.

    The request body never selects tenant or Principal identity. Deployment
    adapters authenticate credentials first and then construct this context.
    Party authority remains a separate tenant-owned decision.
    """

    organization_id: UUID
    principal_id: UUID
    capabilities: frozenset[str]
    principal_kind: PrincipalKind = PrincipalKind.HUMAN
    authentication_method: str = "deployment_adapter"
    correlation_id: UUID = field(default_factory=uuid4)
    credential_id: str | None = None
    platform: str | None = None
    acting_operator_principal_id: UUID | None = None
    technical_principal_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.authentication_method.strip():
            raise ValueError("authentication_method is required")
        if self.credential_id is not None and not self.credential_id.strip():
            raise ValueError("credential_id cannot be blank")
        if self.platform is not None and not self.platform.strip():
            raise ValueError("platform cannot be blank")

    def allows(self, capability: str) -> bool:
        """Evaluate one canonical capability against materialized grants."""

        return any(grant_satisfies(granted, capability) for granted in self.capabilities)
