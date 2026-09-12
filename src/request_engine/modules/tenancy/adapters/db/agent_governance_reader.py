from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceForbidden,
    AgentGovernanceNotFound,
)
from request_engine.modules.tenancy.application.queries.agent_governance import (
    AgentSummary,
    ListAgentsQuery,
)
from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.security.context import ActorContext, PrincipalKind


class PostgresAgentGovernanceReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_agents(
        self, actor: ActorContext, query: ListAgentsQuery
    ) -> tuple[AgentSummary, ...]:
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await self._read(actor, principal_id=None, after=query.after, limit=query.limit)

    async def read_agent(self, actor: ActorContext, principal_id: UUID) -> AgentSummary:
        rows = await self._read(actor, principal_id=principal_id, after=None, limit=1)
        if not rows:
            raise AgentGovernanceNotFound("agent is not visible in this tenant")
        return rows[0]

    async def _read(
        self, actor: ActorContext, *, principal_id: UUID | None, after: UUID | None, limit: int
    ) -> tuple[AgentSummary, ...]:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows("agent.read"):
            raise AgentGovernanceForbidden("agent inspection requires authorized HUMAN authority")
        async with actor_transaction(self._session_factory, actor) as session:
            # Current authority and target data share one MVCC statement snapshot.
            # The outer row distinguishes denial from an authorized empty page.
            rows = (
                (
                    await session.execute(
                        text("""
                    SELECT access.permitted, agent.*
                      FROM (SELECT EXISTS (
                          SELECT 1 FROM request_engine.principals caller
                          JOIN request_engine.principal_authority_grants g
                            ON g.organization_id = caller.organization_id
                           AND g.principal_id = caller.id
                           AND g.capability_key = 'agent.read'
                           AND g.authority_plane = 'tenant_control' AND g.status = 'active'
                         WHERE caller.organization_id = :organization_id
                           AND caller.id = :actor_id AND caller.active
                           AND caller.principal_kind = 'human'
                      ) AS permitted) access
                      LEFT JOIN LATERAL (
                          SELECT a.principal_id, a.display_name, a.purpose,
                                 a.sponsor_principal_id, a.operating_mode, a.status,
                                 a.revision AS profile_revision, p.authority_revision,
                                 p.active AS principal_active,
                                 ARRAY(SELECT g.capability_key
                                     FROM request_engine.principal_authority_grants g
                                    WHERE g.organization_id = a.organization_id
                                      AND g.principal_id = a.principal_id AND g.status = 'active'
                                    ORDER BY g.capability_key) AS standing_capabilities
                            FROM request_engine.agent_profiles a
                            JOIN request_engine.principals p
                              ON p.organization_id = a.organization_id AND p.id = a.principal_id
                           WHERE access.permitted AND a.organization_id = :organization_id
                             AND p.principal_kind = 'agent'
                             AND (CAST(:principal_id AS uuid) IS NULL OR p.id = :principal_id)
                             AND (CAST(:after AS uuid) IS NULL OR p.id > :after)
                           ORDER BY p.id LIMIT :limit
                      ) agent ON true
                     ORDER BY agent.principal_id
                """),
                        {
                            "organization_id": actor.organization_id,
                            "actor_id": actor.principal_id,
                            "principal_id": principal_id,
                            "after": after,
                            "limit": limit,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if not rows[0]["permitted"]:
                raise AgentGovernanceForbidden("agent inspection authority was denied")
            return tuple(
                AgentSummary(
                    principal_id=row["principal_id"],
                    display_name=row["display_name"],
                    purpose=row["purpose"],
                    sponsor_principal_id=row["sponsor_principal_id"],
                    operating_mode=AgentOperatingMode(row["operating_mode"]),
                    status=AgentProfileStatus(row["status"]),
                    principal_active=row["principal_active"],
                    profile_revision=row["profile_revision"],
                    authority_revision=row["authority_revision"],
                    standing_capabilities=tuple(row["standing_capabilities"]),
                )
                for row in rows
                if row["principal_id"] is not None
            )
