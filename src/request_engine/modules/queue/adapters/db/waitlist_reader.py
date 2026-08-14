from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.queue.application.authority import MANAGE_WAITLIST_SCOPE
from request_engine.modules.queue.contracts.waitlist import WaitlistEntry, WaitlistEntryStatus
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresWaitlistEntryReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_waitlist_entry(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        waitlist_entry_id: UUID,
        allow_subject_override: bool,
    ) -> WaitlistEntry | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, offering_id, subject_party_id, location_id,
                                   preferred_resource_id, earliest_start, latest_start,
                                   status, revision, created_at
                            FROM request_engine.waitlist_entries
                            WHERE organization_id = :organization_id
                              AND id = :entry_id
                            """
                        ),
                        {"organization_id": organization_id, "entry_id": waitlist_entry_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None

            subject_party_id = cast(UUID, row["subject_party_id"])
            await require_subject_authority(
                cast(AsyncSession, session),
                organization_id=organization_id,
                principal_id=principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_WAITLIST_SCOPE,
                allow_operator_override=allow_subject_override,
                lock_authority=False,
            )
            return WaitlistEntry(
                id=cast(UUID, row["id"]),
                offering_id=cast(UUID, row["offering_id"]),
                subject_party_id=subject_party_id,
                location_id=cast(UUID | None, row["location_id"]),
                preferred_resource_id=cast(UUID | None, row["preferred_resource_id"]),
                earliest_start=cast(datetime | None, row["earliest_start"]),
                latest_start=cast(datetime | None, row["latest_start"]),
                status=WaitlistEntryStatus(cast(str, row["status"])),
                revision=cast(int, row["revision"]),
                created_at=cast(datetime, row["created_at"]),
            )
