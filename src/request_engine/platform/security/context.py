from dataclasses import dataclass
from uuid import UUID

from request_engine.platform.security.capabilities import grant_satisfies


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated technical actor context supplied by a deployment adapter.

    Business authority remains tenant-owned. This context only carries the
    organization/principal already authenticated by the outer adapter plus the
    materialized capability set the entrypoint may enforce.

    ``allows()`` evaluates canonical V3 capability requirements while accepting
    explicitly registered legacy grant aliases during the pre-baseline transition.
    A technical capability grant never implies Party authority.
    """

    organization_id: UUID
    principal_id: UUID
    capabilities: frozenset[str]

    def allows(self, capability: str) -> bool:
        return any(grant_satisfies(granted, capability) for granted in self.capabilities)
