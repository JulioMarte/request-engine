"""RE-owned acting-operator authority resolution for the trusted relay boundary."""

from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthorityReader,
)
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.context import ActorContext, PrincipalKind


class OperatorCapabilitySource(Protocol):
    """Legacy-named deployment ceiling; it may restrict but never grant RE authority."""

    async def operator_capabilities(
        self, organization_id: UUID, principal_id: UUID
    ) -> frozenset[str]: ...


class DeploymentOperatorActorResolver:
    """Resolve an active HUMAN using RE grants, optionally narrowed by deployment policy."""

    def __init__(
        self,
        authority_reader: PrincipalAuthorityReader,
        capability_source: OperatorCapabilitySource | None = None,
    ) -> None:
        self._authority_reader = authority_reader
        self._capability_source = capability_source

    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None:
        try:
            authority = await self._authority_reader.read_tenant_principal_authority(
                organization_id=organization_id,
                principal_id=principal_id,
            )
        except PrincipalAuthorityMaterializationError as exc:
            raise OperatorResolutionUnavailable() from exc
        if authority is None or authority.principal_kind != PrincipalKind.HUMAN.value:
            return None

        capabilities = authority.capabilities
        if self._capability_source is not None:
            deployment_ceiling = await self._capability_source.operator_capabilities(
                organization_id, principal_id
            )
            capabilities &= deployment_ceiling
        return ActorContext(
            organization_id=organization_id,
            principal_id=principal_id,
            capabilities=capabilities,
            principal_kind=PrincipalKind.HUMAN,
            authority_revision=authority.authority_revision,
        )
