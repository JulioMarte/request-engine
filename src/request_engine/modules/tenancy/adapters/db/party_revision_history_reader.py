"""PostgreSQL party revision history reader (`parties.read_revisions`).

Org-scoped read of the append-only `party_identity_revisions` ledger, ordered
by the per-party monotone `revision`. A Party the organization cannot see
fails closed with the typed not-found, so a foreign tenant learns nothing
about the party's existence. Reads take no locks beyond the tenant RLS
context and require only the SELECT grant.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.errors import PartyNotFound
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryQuery,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyRevision,
    PartySourceKind,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_HISTORY_SQL = text(
    """
    SELECT revision, change_kind, display_name, active, source_kind, platform,
           actor_principal_id, attributed_operator_principal_id, state, created_at
    FROM request_engine.party_identity_revisions
    WHERE organization_id = :organization_id AND party_id = :party_id
    ORDER BY revision
    """
)


class PostgresPartyRevisionHistoryReader:
    """Read-only, tenant-scoped revision ledger reader."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def revision_history(self, query: PartyRevisionHistoryQuery) -> tuple[PartyRevision, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            await _require_party(session, query.organization_id, query.party_id)
            rows = (
                (
                    await session.execute(
                        _HISTORY_SQL,
                        {
                            "organization_id": query.organization_id,
                            "party_id": query.party_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return tuple(_revision_from_row(row) for row in rows)


async def _require_party(session: AsyncSession, organization_id: UUID, party_id: UUID) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.parties"
                " WHERE organization_id = :organization_id AND id = :party_id"
            ),
            {"organization_id": organization_id, "party_id": party_id},
        )
    ).first()
    if row is None:
        raise PartyNotFound(party_id)


def _revision_from_row(row: RowMapping) -> PartyRevision:
    raw_kind = cast(str | None, row["source_kind"])
    return PartyRevision(
        revision=cast(int, row["revision"]),
        change_kind=cast(str, row["change_kind"]),
        display_name=cast(str, row["display_name"]),
        active=cast(bool, row["active"]),
        source_kind=PartySourceKind(raw_kind) if raw_kind else None,
        platform=cast(str | None, row["platform"]),
        actor_principal_id=cast(UUID | None, row["actor_principal_id"]),
        attributed_operator_principal_id=cast(UUID | None, row["attributed_operator_principal_id"]),
        created_at=cast(datetime, row["created_at"]),
        snapshot=cast(dict[str, object], row["state"]),
    )
