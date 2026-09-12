from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.agent_policy import AgentBudgetExceeded


class PostgresAgentBudgetEnforcer:
    """Minute-window agent mutation budget using a race-safe conditional upsert.

    The conditional ``DO UPDATE ... WHERE`` recheck under READ COMMITTED takes
    the row lock before evaluating the limit, so concurrent consumers cannot
    exceed the configured mutation ceiling within one window.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def consume_mutation(
        self, *, organization_id: Any, principal_id: Any, limit: int
    ) -> None:
        window_started_at = datetime.now(UTC).replace(second=0, microsecond=0)
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.agent_budget_windows
                            (organization_id, agent_principal_id, window_started_at,
                             mutation_count)
                        VALUES (:organization_id, :principal_id, :window_started_at, 1)
                        ON CONFLICT (organization_id, agent_principal_id, window_started_at)
                        DO UPDATE SET
                            mutation_count =
                                request_engine.agent_budget_windows.mutation_count + 1
                        WHERE request_engine.agent_budget_windows.mutation_count < :limit
                        RETURNING mutation_count
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "principal_id": principal_id,
                        "window_started_at": window_started_at,
                        "limit": limit,
                    },
                )
            ).fetchone()
        if row is None:
            raise AgentBudgetExceeded("agent mutation budget for the current minute is exhausted")
