from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import TenantReferenceNotUsable


async def require_active_subject_party(
    session: AsyncSession,
    *,
    organization_id: UUID,
    subject_party_id: UUID,
) -> None:
    active = (
        await session.execute(
            text(
                """
                SELECT active
                FROM request_engine.parties
                WHERE organization_id = :organization_id
                  AND id = :subject_party_id
                """
            ),
            {
                "organization_id": organization_id,
                "subject_party_id": subject_party_id,
            },
        )
    ).scalar_one_or_none()
    if active is not True:
        raise TenantReferenceNotUsable("subject_party_id", subject_party_id)


async def require_tenant_reference(
    session: AsyncSession,
    *,
    organization_id: UUID,
    table_name: str,
    reference_kind: str,
    reference_id: UUID | None,
) -> None:
    if reference_id is None:
        return
    allowed_tables = {
        "locations",
        "offerings",
        "reservations",
        "resources",
    }
    if table_name not in allowed_tables:
        raise ValueError(f"unsupported tenant reference table: {table_name}")
    found = (
        await session.execute(
            text(
                f"""
                SELECT 1
                FROM request_engine.{table_name}
                WHERE organization_id = :organization_id
                  AND id = :reference_id
                """
            ),
            {
                "organization_id": organization_id,
                "reference_id": reference_id,
            },
        )
    ).scalar_one_or_none()
    if found is None:
        raise TenantReferenceNotUsable(reference_kind, reference_id)
