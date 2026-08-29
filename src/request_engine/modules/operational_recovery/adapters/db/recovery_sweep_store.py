from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory, tenant_transaction

_DISCOVERY = text(
    "SELECT organization_id, service_queue_id "
    "FROM request_cmd.find_recovery_sweep_scopes(:limit) OFFSET :offset"
)
_CURRENT_REVISION = text(
    "SELECT revision FROM request_engine.recovery_source_revisions "
    "WHERE organization_id = :organization_id AND service_queue_id = :service_queue_id"
)
_LIVE_ACTION = text(
    "SELECT 1 FROM request_engine.scheduled_actions "
    "WHERE organization_id = :organization_id AND dedupe_key = :dedupe_key "
    "AND status IN ('pending', 'leased', 'completed')"
)
_REPAIR_INSERT = text(
    """
    INSERT INTO request_engine.scheduled_actions (
      organization_id, owner_module, action_type, action_version,
      subject_kind, subject_id, payload, dedupe_key,
      execute_at, next_attempt_at, max_attempts
    ) VALUES (
      :organization_id, 'operational_recovery', 'reassess_recovery_scope', 1,
      'ServiceQueue', :service_queue_id,
      jsonb_build_object('service_queue_id', CAST(:service_queue_id_text AS text),
                         'source_revision', CAST(:revision AS bigint)),
      :dedupe_key, clock_timestamp(), clock_timestamp(), 8
    )
    ON CONFLICT (organization_id, dedupe_key) DO NOTHING
    """
)


@dataclass(frozen=True, slots=True)
class RecoverySweepScope:
    organization_id: UUID
    service_queue_id: UUID


def reassessment_dedupe_key(service_queue_id: UUID, revision: int) -> str:
    return f"f5-reassessment:{service_queue_id}:{revision}"


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
        async with tenant_transaction(
            self._domain_session_factory, scope.organization_id
        ) as session:
            revision = await _current_revision(session, scope)
            if revision is None:
                return False
            key = reassessment_dedupe_key(scope.service_queue_id, revision)
            if await _has_live_action(session, scope.organization_id, key):
                return False
            result = cast(
                CursorResult[Any],
                await session.execute(
                    _REPAIR_INSERT,
                    {
                        "organization_id": scope.organization_id,
                        "service_queue_id": scope.service_queue_id,
                        "service_queue_id_text": str(scope.service_queue_id),
                        "revision": revision,
                        "dedupe_key": key,
                    },
                ),
            )
            return bool(result.rowcount)


async def _current_revision(session: AsyncSession, scope: RecoverySweepScope) -> int | None:
    row = (
        await session.execute(
            _CURRENT_REVISION,
            {
                "organization_id": scope.organization_id,
                "service_queue_id": scope.service_queue_id,
            },
        )
    ).scalar_one_or_none()
    return row


async def _has_live_action(session: AsyncSession, organization_id: UUID, key: str) -> bool:
    return (
        await session.execute(_LIVE_ACTION, {"organization_id": organization_id, "dedupe_key": key})
    ).first() is not None
