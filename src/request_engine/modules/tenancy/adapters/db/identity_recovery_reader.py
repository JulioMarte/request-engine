from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.queries.identity_recovery import (
    GetIdentityRecoveryCaseQuery,
    IdentityRecoveryCaseView,
    IdentityRecoveryReadError,
    IdentityRecoveryReadForbidden,
    IdentityRecoveryReadInvalid,
    ListIdentityRecoveryCasesQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_CAPABILITY = "platform.identity.read"
_READ_ERRORS: dict[str, type[IdentityRecoveryReadError]] = {
    "22023": IdentityRecoveryReadInvalid,
    "42501": IdentityRecoveryReadForbidden,
    "28000": IdentityRecoveryReadForbidden,
}


class PostgresIdentityRecoveryReader:
    """Read recovery cases through the bounded platform read projection."""

    def __init__(self, read_session_factory: SessionFactory) -> None:
        self._read_session_factory = read_session_factory

    async def list_cases(
        self,
        actor: PlatformActorContext,
        query: ListIdentityRecoveryCasesQuery,
    ) -> list[IdentityRecoveryCaseView]:
        _authorize(actor)
        rows = await self._read(case_id=None, after=query.after, limit=query.limit)
        return [_materialize(row) for row in rows]

    async def get_case(
        self,
        actor: PlatformActorContext,
        query: GetIdentityRecoveryCaseQuery,
    ) -> IdentityRecoveryCaseView | None:
        _authorize(actor)
        rows = await self._read(case_id=query.case_id, after=None, limit=1)
        if not rows:
            return None
        return _materialize(rows[0])

    async def _read(
        self,
        *,
        case_id: UUID | None,
        after: UUID | None,
        limit: int,
    ) -> list[Sequence[Any]]:
        try:
            async with self._read_session_factory() as session, session.begin():
                rows = (
                    await session.execute(
                        text("""
                            SELECT * FROM request_platform.read_identity_recovery_cases(
                                CAST(:case_id AS uuid),
                                CAST(:after AS uuid),
                                CAST(:limit AS integer)
                            )
                            """),
                        {"case_id": case_id, "after": after, "limit": limit},
                    )
                ).all()
        except DBAPIError as exc:
            error_type = _READ_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
            if error_type is None:
                raise
            raise error_type() from None
        return [tuple(row) for row in rows]


def _authorize(actor: PlatformActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(_CAPABILITY):
        raise IdentityRecoveryReadForbidden(_CAPABILITY)


def _materialize(row: Sequence[Any]) -> IdentityRecoveryCaseView:
    return IdentityRecoveryCaseView(
        case_id=UUID(str(row[0])),
        target_native_identity_id=UUID(str(row[1])),
        status=str(row[2]),
        delivery_status=str(row[3]),
        revision=int(row[4]),
        issuance_generation=int(row[5]),
        approval_expires_at=row[6],
        proof_expires_at=row[7],
        created_at=row[8],
        approved_at=row[9],
        issued_at=row[10],
        consumed_at=row[11],
        revoked_at=row[12],
    )
