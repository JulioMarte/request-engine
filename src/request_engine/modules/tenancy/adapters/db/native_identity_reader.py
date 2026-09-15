from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.queries.native_identity_read import (
    NATIVE_IDENTITY_READ_CAPABILITY,
    GetNativeIdentityQuery,
    ListNativeIdentitiesQuery,
    NativeIdentityReadForbidden,
    NativeIdentityReadInvalid,
    NativeIdentityReadNotFound,
    NativeIdentityView,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_READ_ERRORS: dict[str, type[Exception]] = {
    "22023": NativeIdentityReadInvalid,
    "42501": NativeIdentityReadForbidden,
    "28000": NativeIdentityReadForbidden,
}


def _authorize(actor: PlatformActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
        NATIVE_IDENTITY_READ_CAPABILITY
    ):
        raise NativeIdentityReadForbidden(NATIVE_IDENTITY_READ_CAPABILITY)


def _materialize(row: Any) -> NativeIdentityView:
    return NativeIdentityView(
        native_identity_id=row[0],
        identity_authority_id=row[1],
        status=str(row[2]),
        revision=int(row[3]),
        created_at=row[4],
        disabled_at=row[5],
    )


class PostgresNativeIdentityReader:
    """Private native-identity projection through the read-only platform login."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_identities(
        self,
        actor: PlatformActorContext,
        query: ListNativeIdentitiesQuery,
    ) -> tuple[NativeIdentityView, ...]:
        _authorize(actor)
        rows = await self._read(identity_id=None, after=query.after, limit=query.limit)
        return tuple(_materialize(row) for row in rows)

    async def read_identity(
        self,
        actor: PlatformActorContext,
        query: GetNativeIdentityQuery,
    ) -> NativeIdentityView:
        _authorize(actor)
        rows = await self._read(identity_id=query.native_identity_id, after=None, limit=1)
        if not rows:
            raise NativeIdentityReadNotFound("native identity was not found")
        return _materialize(rows[0])

    async def _read(self, *, identity_id: Any, after: Any, limit: int) -> list[Any]:
        async with self._session_factory() as session:
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT * FROM request_platform.read_native_identities(
                            CAST(:identity_id AS uuid),
                            CAST(:after AS uuid),
                            CAST(:limit AS integer)
                        )
                        """
                    ),
                    {"identity_id": identity_id, "after": after, "limit": limit},
                )
            except DBAPIError as exc:
                error_type = _READ_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
                if error_type is None:
                    raise
                raise error_type() from None
            return list(result.all())
