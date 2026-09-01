"""DB-backed deployment adapter for the acting-operator relay port (§9.1).

Deployments that admit `platform.acting_for_operator` resolve the referenced
operator against authoritative `request_engine.principals` state on the same
database surface the app serves: the principal must exist, belong to the
relay's organization, be active and be a HUMAN principal. Capability
materialization stays with the deployment's own grant model — the same source
its authentication adapter uses to build `ActorContext.capabilities` for human
actors — through `OperatorCapabilitySource`; this adapter never invents
grants. Anything unresolvable returns None and the relay fails closed with
the platform 403; a deployment that cannot materialize the operator grant set
at all fails with `OperatorResolutionUnavailable` (misconfiguration, not a
permission denial).
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.context import ActorContext, PrincipalKind


class OperatorCapabilitySource(Protocol):
    """Deployment grant materialization for one human operator principal."""

    async def operator_capabilities(
        self, organization_id: UUID, principal_id: UUID
    ) -> frozenset[str]: ...


class DeploymentOperatorActorResolver:
    """Resolve an admitted acting operator from authoritative principal state."""

    def __init__(
        self,
        session_factory: SessionFactory,
        capability_source: OperatorCapabilitySource | None,
    ) -> None:
        self._session_factory = session_factory
        self._capability_source = capability_source

    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None:
        if self._capability_source is None:
            raise OperatorResolutionUnavailable()
        row = await self._principal_row(organization_id, principal_id)
        if row is None or not row["active"] or row["principal_kind"] != "human":
            return None
        capabilities = await self._capability_source.operator_capabilities(
            organization_id, principal_id
        )
        return ActorContext(
            organization_id=organization_id,
            principal_id=principal_id,
            capabilities=capabilities,
            principal_kind=PrincipalKind.HUMAN,
        )

    async def _principal_row(self, organization_id: UUID, principal_id: UUID) -> RowMapping | None:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            return (
                (
                    await session.execute(
                        text(
                            "SELECT principal_kind, active FROM request_engine.principals"
                            " WHERE organization_id = :organization_id AND id = :principal_id"
                        ),
                        {"organization_id": organization_id, "principal_id": principal_id},
                    )
                )
                .mappings()
                .first()
            )
