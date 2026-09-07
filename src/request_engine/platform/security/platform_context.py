from dataclasses import dataclass, field
from uuid import UUID, uuid4

from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.context import PrincipalKind


@dataclass(frozen=True, slots=True)
class PlatformActorContext:
    """Trusted platform-control actor with no tenant scope.

    Platform actors are structurally distinct from tenant ``ActorContext``:
    they carry no ``organization_id`` and may materialize only canonical
    PLATFORM-plane capabilities. Crossing into a tenant therefore requires an
    explicit provisioning/selection transition rather than nullable tenant
    identity leaking through ordinary business routes.
    """

    principal_id: UUID
    capabilities: frozenset[str]
    authority_revision: int
    principal_kind: PrincipalKind = PrincipalKind.HUMAN
    authentication_method: str = "deployment_adapter"
    correlation_id: UUID = field(default_factory=uuid4)
    credential_id: str | None = None
    technical_principal_id: UUID | None = None
    interaction_id: str | None = None

    def __post_init__(self) -> None:
        if self.authority_revision <= 0:
            raise ValueError("authority_revision must be positive")
        if not self.authentication_method.strip():
            raise ValueError("authentication_method is required")
        if self.credential_id is not None and not self.credential_id.strip():
            raise ValueError("credential_id cannot be blank")
        if self.interaction_id is not None and not self.interaction_id.strip():
            raise ValueError("interaction_id cannot be blank")
        for capability in self.capabilities:
            definition = capability_definition(capability)
            if definition is None:
                raise ValueError(f"unknown platform capability: {capability}")
            if definition.authority_plane is not AuthorityPlane.PLATFORM:
                raise ValueError(f"non-platform capability in platform context: {capability}")

    def allows(self, capability: str) -> bool:
        """Require exact canonical platform authority; aliases never elevate control-plane access."""

        definition = capability_definition(capability)
        return (
            definition is not None
            and definition.authority_plane is AuthorityPlane.PLATFORM
            and capability in self.capabilities
        )
