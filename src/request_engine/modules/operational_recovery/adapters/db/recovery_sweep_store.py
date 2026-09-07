from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory, tenant_transaction

_DISCOVERY = text(
    "SELECT organization_id, service_queue_id "
    "FROM request_cmd.find_recovery_sweep_scopes(:limit) OFFSET :offset"
)
_CURRENT_REVISION = text(
    "SELECT request_read.recovery_source_revision(:organization_id, :service_queue_id)"
)
_SCHEDULE_REASSESSMENT = text(
    "SELECT request_cmd.schedule_recovery_reassessment("
    ":organization_id, :service_queue_id, :revision)"
)


@dataclass(frozen=True, slots=True)
class RecoverySweepScope:
    organization_id: UUID
    service_queue_id: UUID


class PostgresRecoverySweepStore:
    """Discover scopes cross-tenant; repair each wake-up under normal tenant RLS."""

    def __init__(
        self,
        worker_session_factory: SessionFactory,
        domain_session_factory: SessionFactory,
    ) -> None:
        self._worker_session_factory = worker_session_factory
        self._domain_session_factory = domain_session_factory

    async def find_scopes(self, *, limit: int, offset: int) -> list[RecoverySweepScope]:
        async with self._worker_session_factory() as session:
            rows = (await session.execute(_DISCOVERY, {"limit": limit, "offset": offset})).all()
        return [RecoverySweepScope(organization_id=row[0], service_queue_id=row[1]) for row in rows]

    async def repair_scope(self, scope: RecoverySweepScope) -> bool:
        """Re-enqueue the scope's current revision through the shared coalescing
        enqueue; the per-revision dedupe conflict makes live or terminal actions
        a no-op and cancelled actions are never resurrected."""

        async with tenant_transaction(
            self._domain_session_factory, scope.organization_id
        ) as session:
            revision = await _current_revision(session, scope)
            if revision is None:
                return False
            row = await session.execute(
                _SCHEDULE_REASSESSMENT,
                {
                    "organization_id": scope.organization_id,
                    "service_queue_id": scope.service_queue_id,
                    "revision": revision,
                },
            )
            return bool(row.scalar_one())


async def _current_revision(session: AsyncSession, scope: RecoverySweepScope) -> int | None:
    return (
        await session.execute(
            _CURRENT_REVISION,
            {
                "organization_id": scope.organization_id,
                "service_queue_id": scope.service_queue_id,
            },
        )
    ).scalar_one_or_none()
