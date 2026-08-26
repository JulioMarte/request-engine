from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import TenantReferenceNotUsable


async def require_active_subject(
    session: AsyncSession, organization_id: UUID, subject_id: UUID
) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.parties "
                "WHERE organization_id=:organization_id AND id=:subject_id AND active"
            ),
            {"organization_id": organization_id, "subject_id": subject_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("subject_party_id", subject_id)


async def require_offering(session: AsyncSession, organization_id: UUID, offering_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.offerings "
                "WHERE organization_id=:organization_id AND id=:offering_id AND active"
            ),
            {"organization_id": organization_id, "offering_id": offering_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("offering_id", offering_id)


async def require_active_workload(
    session: AsyncSession, organization_id: UUID, workload_id: UUID | None
) -> None:
    if workload_id is None:
        return
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.operational_workload_classifications "
                "WHERE organization_id=:organization_id AND id=:workload_id AND active"
            ),
            {"organization_id": organization_id, "workload_id": workload_id},
        )
    ).first()
    if row is None:
        raise TenantReferenceNotUsable("expected_workload_classification_id", workload_id)


async def require_reservation_match(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    subject_party_id: UUID,
    queue_location_id: UUID | None,
    queue_offering_id: UUID | None,
) -> UUID:
    row = (
        (
            await session.execute(
                text(
                    "SELECT r.subject_party_id,r.location_id,ov.offering_id "
                    "FROM request_engine.reservations r "
                    "JOIN request_engine.offering_versions ov "
                    "ON ov.organization_id=r.organization_id AND ov.id=r.offering_version_id "
                    "WHERE r.organization_id=:organization_id AND r.id=:reservation_id "
                    "AND r.status='confirmed'"
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["subject_party_id"] != subject_party_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    if queue_location_id is not None and row["location_id"] != queue_location_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    offering_id = cast(UUID, row["offering_id"])
    if queue_offering_id is not None and offering_id != queue_offering_id:
        raise TenantReferenceNotUsable("reservation_id", reservation_id)
    return offering_id
