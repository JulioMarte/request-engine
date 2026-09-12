from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from request_engine.platform.security.agent_policy import AgentPolicySnapshot
from request_engine.platform.security.capabilities import grant_satisfies


class PrincipalKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    INTEGRATION = "integration"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Trusted execution identity produced by an authentication adapter.

    ``principal_id`` is the security actor that is executing the operation for
    ordinary HUMAN/AGENT/INTEGRATION/SYSTEM requests. ``subject_principal_id``
    records a distinct requesting authority only when one is intentionally
    represented. ``technical_principal_id`` remains the transport/workload
    identity when a trusted relay is distinct from the effective actor.

    Request bodies never select tenant, Principal, delegation, or authority
    identity. Deployment adapters authenticate credentials and construct this
    context from Request Engine-owned authority state.
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
    subject_principal_id: UUID | None = None
    delegation_id: UUID | None = None
    authority_revision: int | None = None
    interaction_id: str | None = None
    agent_policy: AgentPolicySnapshot | None = None

    def __post_init__(self) -> None:
        if not self.authentication_method.strip():
            raise ValueError("authentication_method is required")
        if self.credential_id is not None and not self.credential_id.strip():
            raise ValueError("credential_id cannot be blank")
        if self.platform is not None and not self.platform.strip():
            raise ValueError("platform cannot be blank")
        if self.authority_revision is not None and self.authority_revision <= 0:
            raise ValueError("authority_revision must be positive")
        if self.interaction_id is not None and not self.interaction_id.strip():
            raise ValueError("interaction_id cannot be blank")
        if self.subject_principal_id == self.principal_id:
            raise ValueError(
                "subject_principal_id must be omitted when actor and subject are identical"
            )

    def allows(self, capability: str) -> bool:
        """Evaluate one canonical capability against materialized grants."""

        return any(grant_satisfies(granted, capability) for granted in self.capabilities)
