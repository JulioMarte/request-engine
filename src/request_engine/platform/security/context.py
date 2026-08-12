from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated technical actor context supplied by a deployment adapter.

    Business authority remains tenant-owned. This context only carries the
    organization/principal already authenticated by the outer adapter plus the
    materialized capability set the entrypoint may enforce.
    """

    organization_id: UUID
    principal_id: UUID
    capabilities: frozenset[str]

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities
