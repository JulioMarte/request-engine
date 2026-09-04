from uuid import UUID

from sqlalchemy import text

from request_engine.modules.queue.contracts.onboarding import QueueOnboardingSupply
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresQueueOnboardingReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_queue_supply(self, *, organization_id: UUID) -> QueueOnboardingSupply:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            queue_count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM request_engine.service_queues
                        WHERE organization_id = :organization_id AND active
                        """
                    ),
                    {"organization_id": organization_id},
                )
            ).scalar_one()
            return QueueOnboardingSupply(active_queue_count=int(queue_count))
