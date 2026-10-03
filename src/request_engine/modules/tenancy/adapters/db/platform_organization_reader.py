from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.queries.platform_organization_read import (
    PLATFORM_ORGANIZATION_READ_CAPABILITY,
    GetPlatformOrganizationQuery,
    ListPlatformOrganizationsQuery,
    PlatformOrganizationReadForbidden,
    PlatformOrganizationReadInvalid,
    PlatformOrganizationReadNotFound,
    PlatformOrganizationSummary,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_READ_ERRORS: dict[str, type[Exception]] = {
    "22023": PlatformOrganizationReadInvalid,
    "42501": PlatformOrganizationReadForbidden,
    "28000": PlatformOrganizationReadForbidden,
}


class PostgresPlatformOrganizationReader:
    """Read organizations through the private, audited platform projection."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_organizations(
        self,
        actor: PlatformActorContext,
        query: ListPlatformOrganizationsQuery,
    ) -> tuple[PlatformOrganizationSummary, ...]:
        _authorize(actor)
        rows = await self._read(organization_id=None, after=query.after, limit=query.limit)
        return tuple(_materialize(row) for row in rows)

    async def get_organization(
        self,
        actor: PlatformActorContext,
        query: GetPlatformOrganizationQuery,
    ) -> PlatformOrganizationSummary:
        _authorize(actor)
        rows = await self._read(organization_id=query.organization_id, after=None, limit=1)
        if not rows:
            raise PlatformOrganizationReadNotFound("organization was not found")
        return _materialize(rows[0])

    async def _read(
        self,
        *,
        organization_id: object,
        after: object,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        async with self._session_factory() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT organization_id,
                               organization_key,
                               display_name,
                               operational_status,
                               default_timezone,
                               default_locale,
                               default_currency,
                               created_at,
                               updated_at
                          FROM request_platform.read_platform_organizations(
                              CAST(:organization_id AS uuid),
                              CAST(:after AS uuid),
                              CAST(:limit AS integer)
                          )
                        """
                    ),
                    {"organization_id": organization_id, "after": after, "limit": limit},
                )
            except DBAPIError as exc:
                error_type = _READ_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
                if error_type is None:
                    raise
                raise error_type() from None
            return [dict(row) for row in result.mappings().all()]


def _authorize(actor: PlatformActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
        PLATFORM_ORGANIZATION_READ_CAPABILITY
    ):
        raise PlatformOrganizationReadForbidden(PLATFORM_ORGANIZATION_READ_CAPABILITY)


def _materialize(row: Mapping[str, Any]) -> PlatformOrganizationSummary:
    return PlatformOrganizationSummary(
        organization_id=UUID(str(row["organization_id"])),
        organization_key=str(row["organization_key"]),
        display_name=str(row["display_name"]),
        operational_status=str(row["operational_status"]),
        default_timezone=None if row["default_timezone"] is None else str(row["default_timezone"]),
        default_locale=None if row["default_locale"] is None else str(row["default_locale"]),
        default_currency=None if row["default_currency"] is None else str(row["default_currency"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
