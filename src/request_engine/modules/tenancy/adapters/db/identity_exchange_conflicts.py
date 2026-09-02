"""Narrow PostgreSQL conflict classification for S0d identity adoption."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.identity_exchange_sql import (
    EXISTING_BOUND_PARTY,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_BINDING_PERSON_UNIQUE = "organization_person_binding_person_uq"
_UNIQUE_SQLSTATE = "23505"


def is_identity_already_adopted_violation(exc: IntegrityError) -> bool:
    if getattr(exc.orig, "sqlstate", None) != _UNIQUE_SQLSTATE:
        return False
    diagnostic = getattr(exc.orig, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint is not None:
        return constraint == _BINDING_PERSON_UNIQUE
    return f'"{_BINDING_PERSON_UNIQUE}"' in str(exc.orig)


async def existing_adopted_party(
    session_factory: SessionFactory,
    organization_id: UUID,
    candidate_ref: UUID,
    principal_id: UUID,
) -> UUID | None:
    async with tenant_transaction(session_factory, organization_id) as session:
        value = (
            await session.execute(
                EXISTING_BOUND_PARTY,
                {
                    "candidate_ref": candidate_ref,
                    "principal_id": principal_id,
                },
            )
        ).scalar_one_or_none()
    return UUID(str(value)) if value is not None else None
