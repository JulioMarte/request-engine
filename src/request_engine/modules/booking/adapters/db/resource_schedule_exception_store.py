from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
)


async def require_resource_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    expected_revision: int,
) -> int:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT active, availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id
                      AND id = :resource_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ContextualConfigurationConflict(
            "Resource is missing or belongs to another Organization"
        )
    if not cast(bool, row["active"]):
        raise ContextualConfigurationConflict(
            "Resource must be active to configure schedule exceptions"
        )
    current_revision = cast(int, row["availability_revision"])
    if current_revision != expected_revision:
        raise ResourceAvailabilityRevisionConflict(resource_id, expected_revision, current_revision)
    return current_revision


async def upsert_exception(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    exception_id: UUID | None,
    start_at: datetime,
    end_at: datetime,
    exception_kind: str,
    reason: str | None,
) -> UUID:
    params = {
        "organization_id": organization_id,
        "resource_id": resource_id,
        "exception_id": exception_id,
        "start_at": start_at,
        "end_at": end_at,
        "exception_kind": exception_kind,
        "reason": reason,
    }
    if exception_id is None:
        statement = """
            INSERT INTO request_engine.schedule_exceptions (
                organization_id, resource_id, during, exception_kind, reason
            ) VALUES (
                :organization_id, :resource_id,
                tstzrange(:start_at, :end_at, '[)'), :exception_kind, :reason
            ) RETURNING id
        """
    else:
        statement = """
            UPDATE request_engine.schedule_exceptions
               SET during = tstzrange(:start_at, :end_at, '[)'),
                   exception_kind = :exception_kind,
                   reason = :reason
             WHERE organization_id = :organization_id
               AND id = :exception_id
               AND resource_id = :resource_id
            RETURNING id
        """
    row = (await session.execute(text(statement), params)).first()
    if row is None:
        raise ContextualConfigurationConflict(
            "schedule exception is missing or belongs to another Resource"
        )
    return cast(UUID, row[0])


async def availability_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id AND id = :resource_id
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        ).scalar_one(),
    )
