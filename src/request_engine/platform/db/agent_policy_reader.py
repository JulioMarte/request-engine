from typing import Any

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.agent_policy import AgentPolicySnapshot
from request_engine.platform.security.operation_risk import OperationRiskClass


class PostgresAgentPolicyReader:
    """Tenant-scoped agent tool/risk policy reads under RLS."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_policy(
        self, *, organization_id: Any, principal_id: Any
    ) -> AgentPolicySnapshot | None:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            row = (
                await session.execute(
                    text(
                        """
                        SELECT allowed_capabilities, denied_capabilities, risk_ceiling,
                               max_mutations_per_minute, policy_revision
                          FROM request_engine.agent_policies
                         WHERE agent_principal_id = :principal_id
                        """
                    ),
                    {"principal_id": principal_id},
                )
            ).fetchone()
        if row is None:
            return None
        return AgentPolicySnapshot(
            allowed_capabilities=frozenset(row[0]),
            denied_capabilities=frozenset(row[1]),
            risk_ceiling=OperationRiskClass(row[2]),
            max_mutations_per_minute=row[3],
            policy_revision=row[4],
        )
