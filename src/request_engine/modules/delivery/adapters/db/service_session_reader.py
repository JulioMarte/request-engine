from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.delivery.application.errors import ServiceSessionNotFound
from request_engine.modules.delivery.contracts.service_session import (
    InterruptionKind,
    ServiceSession,
    ServiceSessionInterruption,
    ServiceSessionOperationalSnapshot,
    ServiceSessionStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresServiceSessionReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        organization_id: UUID,
        service_session_id: UUID,
    ) -> ServiceSessionOperationalSnapshot:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT service_session_id AS id, queue_entry_id,
                                   resource_id, location_id,
                                   actual_workload_classification_id, status,
                                   started_at, completed_at, revision,
                                   interruption_seconds, clock_timestamp() AS observed_at
                              FROM request_read.service_session_status_v1
                             WHERE organization_id = :organization_id
                               AND service_session_id = :service_session_id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "service_session_id": service_session_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ServiceSessionNotFound(service_session_id)
            interruption_rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, service_session_id, kind, started_at, ended_at
                              FROM request_engine.service_session_interruptions
                             WHERE organization_id = :organization_id
                               AND service_session_id = :service_session_id
                             ORDER BY started_at, id
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "service_session_id": service_session_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        started_at = cast(datetime, row["started_at"])
        completed_at = cast(datetime | None, row["completed_at"])
        observed_at = cast(datetime, row["observed_at"])
        wall_clock_seconds = max(
            0,
            int(((completed_at or observed_at) - started_at).total_seconds()),
        )
        interruption_seconds = cast(int, row["interruption_seconds"])
        service = ServiceSession(
            id=cast(UUID, row["id"]),
            queue_entry_id=cast(UUID, row["queue_entry_id"]),
            resource_id=cast(UUID, row["resource_id"]),
            location_id=cast(UUID, row["location_id"]),
            status=ServiceSessionStatus(cast(str, row["status"])),
            started_at=started_at,
            completed_at=completed_at,
            actual_workload_classification_id=cast(
                UUID | None,
                row["actual_workload_classification_id"],
            ),
            revision=cast(int, row["revision"]),
        )
        interruptions = tuple(
            ServiceSessionInterruption(
                id=cast(UUID, item["id"]),
                service_session_id=cast(UUID, item["service_session_id"]),
                kind=InterruptionKind(cast(str, item["kind"])),
                started_at=cast(datetime, item["started_at"]),
                ended_at=cast(datetime | None, item["ended_at"]),
            )
            for item in interruption_rows
        )
        return ServiceSessionOperationalSnapshot(
            session=service,
            observed_at=observed_at,
            wall_clock_seconds=wall_clock_seconds,
            interruption_seconds=interruption_seconds,
            active_service_seconds=max(0, wall_clock_seconds - interruption_seconds),
            interruptions=interruptions,
        )
