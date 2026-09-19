from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.tenancy.application.queries.platform_provisioner_read import (
    GetPlatformProvisionerQuery,
    ListPlatformProvisionersQuery,
    PlatformProvisionerReadForbidden,
    PlatformProvisionerSummary,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_CAPABILITY = "platform.provisioner.read"


class PostgresPlatformProvisionerReader:
    """Read provisioners only through the audited platform read projection."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_provisioners(
        self,
        actor: PlatformActorContext,
        query: ListPlatformProvisionersQuery,
    ) -> tuple[PlatformProvisionerSummary, ...]:
        _authorize(actor)
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        rows = await self._read(principal_id=None, after=query.after, limit=query.limit)
        return tuple(_materialize(row) for row in rows)

    async def get_provisioner(
        self,
        actor: PlatformActorContext,
        query: GetPlatformProvisionerQuery,
    ) -> PlatformProvisionerSummary | None:
        _authorize(actor)
        rows = await self._read(principal_id=query.principal_id, after=None, limit=1)
        if not rows:
            return None
        return _materialize(rows[0])

    async def _read(
        self,
        *,
        principal_id: UUID | None,
        after: UUID | None,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text("""
                        SELECT principal_id,
                               principal_kind,
                               active,
                               authority_revision,
                               binding_id,
                               binding_status,
                               identity_authority_id,
                               binding_subject_id,
                               capabilities,
                               provenance_reference,
                               granted_at
                          FROM request_platform.read_platform_provisioners(
                              CAST(:principal_id AS uuid),
                              CAST(:after AS uuid),
                              CAST(:limit AS integer)
                          )
                        """),
                        {"principal_id": principal_id, "after": after, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]


def _authorize(actor: PlatformActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(_CAPABILITY):
        raise PlatformProvisionerReadForbidden(_CAPABILITY)


def _materialize(row: Mapping[str, Any]) -> PlatformProvisionerSummary:
    capabilities = cast(list[object], row["capabilities"] or [])
    return PlatformProvisionerSummary(
        principal_id=UUID(str(row["principal_id"])),
        principal_kind=str(row["principal_kind"]),
        active=bool(row["active"]),
        authority_revision=int(row["authority_revision"]),
        binding_id=None if row["binding_id"] is None else UUID(str(row["binding_id"])),
        binding_status=None if row["binding_status"] is None else str(row["binding_status"]),
        identity_authority_id=None
        if row["identity_authority_id"] is None
        else UUID(str(row["identity_authority_id"])),
        binding_subject_id=None
        if row["binding_subject_id"] is None
        else str(row["binding_subject_id"]),
        capabilities=tuple(str(capability) for capability in capabilities),
        provenance_reference=None
        if row["provenance_reference"] is None
        else str(row["provenance_reference"]),
        granted_at=row["granted_at"],
    )
