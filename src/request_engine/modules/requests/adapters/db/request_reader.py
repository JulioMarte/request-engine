from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.requests.adapters.db.party_authority import require_requester_authority
from request_engine.modules.requests.contracts.request import (
    ExternalCorrelation,
    Request,
    RequestParticipant,
    RequestStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresRequestReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_request(
        self,
        organization_id: UUID,
        principal_id: UUID,
        request_id: UUID,
        *,
        allow_party_override: bool,
    ) -> Request | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = await read_request_row(session, organization_id, request_id)
            if row is None:
                return None
            await require_requester_authority(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                requester_party_id=cast(UUID | None, row["requester_party_id"]),
                scope_key="requests.manage",
                allow_operator_override=allow_party_override,
            )
            participants = await read_participants(session, organization_id, request_id)
            correlations = await read_correlations(session, organization_id, request_id)
        return request_from_row(
            row,
            participants=participants,
            correlations=correlations,
        )


async def read_request_row(
    session: AsyncSession,
    organization_id: UUID,
    request_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, request_definition_version_id,
                           requester_party_id, recipient_party_id,
                           status, payload, result_payload, revision,
                           created_at, completed_at, updated_at
                    FROM request_engine.requests
                    WHERE organization_id = :organization_id
                      AND id = :request_id
                    """
                ),
                {"organization_id": organization_id, "request_id": request_id},
            )
        )
        .mappings()
        .first()
    )


async def read_request(
    session: AsyncSession,
    organization_id: UUID,
    request_id: UUID,
) -> Request:
    row = await read_request_row(session, organization_id, request_id)
    if row is None:
        raise LookupError(f"Request {request_id} disappeared inside its transaction")
    participants = await read_participants(session, organization_id, request_id)
    correlations = await read_correlations(session, organization_id, request_id)
    return request_from_row(
        row,
        participants=participants,
        correlations=correlations,
    )


async def read_participants(
    session: AsyncSession,
    organization_id: UUID,
    request_id: UUID,
) -> tuple[RequestParticipant, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT party_id, role_key
                    FROM request_engine.request_participants
                    WHERE organization_id = :organization_id
                      AND request_id = :request_id
                    ORDER BY role_key, party_id
                    """
                ),
                {"organization_id": organization_id, "request_id": request_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        RequestParticipant(
            party_id=cast(UUID, row["party_id"]),
            role_key=cast(str, row["role_key"]),
        )
        for row in rows
    )


async def read_correlations(
    session: AsyncSession,
    organization_id: UUID,
    request_id: UUID,
) -> tuple[ExternalCorrelation, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, correlation_kind, provider_key, external_key
                    FROM request_engine.external_correlations
                    WHERE organization_id = :organization_id
                      AND request_id = :request_id
                    ORDER BY correlation_kind, provider_key, external_key, id
                    """
                ),
                {"organization_id": organization_id, "request_id": request_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        ExternalCorrelation(
            id=cast(UUID, row["id"]),
            correlation_kind=cast(str, row["correlation_kind"]),
            provider_key=cast(str, row["provider_key"]),
            external_key=cast(str, row["external_key"]),
        )
        for row in rows
    )


def request_from_row(
    row: RowMapping,
    *,
    participants: tuple[RequestParticipant, ...] = (),
    correlations: tuple[ExternalCorrelation, ...] = (),
) -> Request:
    return Request(
        id=cast(UUID, row["id"]),
        request_definition_version_id=cast(UUID, row["request_definition_version_id"]),
        requester_party_id=cast(UUID | None, row["requester_party_id"]),
        recipient_party_id=cast(UUID | None, row["recipient_party_id"]),
        status=RequestStatus(cast(str, row["status"])),
        payload=cast(dict[str, object], row["payload"]),
        result_payload=cast(dict[str, object] | None, row["result_payload"]),
        revision=cast(int, row["revision"]),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        participants=participants,
        correlations=correlations,
    )
