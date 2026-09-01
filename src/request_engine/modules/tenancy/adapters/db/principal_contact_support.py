"""Row/locking/code plumbing for the staff principal contact commands (§9.2).

The one-time code is stored only as a sha256 hash and carried verbatim only
in the outbox payload; rows are locked through the principal-scoped
predicate, so another principal's contact is not visible to these commands.
"""

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.errors import PrincipalContactNotFound

MAX_VERIFICATION_ATTEMPTS = 5

_INSERT_SQL = text(
    "INSERT INTO request_engine.principal_contacts"
    " (organization_id, principal_id, channel, normalized_value, created_by_principal_id)"
    " VALUES (:organization_id, :principal_id, :channel, :normalized_value, :principal_id)"
    " RETURNING id, channel, normalized_value, verified, active"
)

_LOCK_SQL = text(
    "SELECT id, channel, normalized_value, verified, active, verification_code_hash,"
    " verification_expires_at, verification_attempts"
    " FROM request_engine.principal_contacts"
    " WHERE organization_id = :organization_id AND principal_id = :principal_id"
    " AND id = :contact_id FOR UPDATE"
)

_SET_PENDING_SQL = text(
    "UPDATE request_engine.principal_contacts"
    " SET verification_code_hash = :code_hash, verification_expires_at = :expires_at,"
    " verification_attempts = 0"
    " WHERE organization_id = :organization_id AND principal_id = :principal_id"
    " AND id = :contact_id"
)

_MARK_VERIFIED_SQL = text(
    "UPDATE request_engine.principal_contacts"
    " SET verified = TRUE, verification_code_hash = NULL, verification_expires_at = NULL,"
    " verification_attempts = 0"
    " WHERE organization_id = :organization_id AND principal_id = :principal_id"
    " AND id = :contact_id"
)

_BUMP_ATTEMPTS_SQL = text(
    "UPDATE request_engine.principal_contacts"
    " SET verification_attempts = verification_attempts + 1"
    " WHERE organization_id = :organization_id AND principal_id = :principal_id"
    " AND id = :contact_id"
    " RETURNING verification_attempts"
)


def _keyed(organization_id: UUID, principal_id: UUID, contact_id: UUID) -> dict[str, object]:
    return {
        "organization_id": organization_id,
        "principal_id": principal_id,
        "contact_id": contact_id,
    }


def new_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def insert_contact(
    session: AsyncSession,
    organization_id: UUID,
    principal_id: UUID,
    channel: str,
    normalized_value: str,
) -> RowMapping:
    return (
        (
            await session.execute(
                _INSERT_SQL,
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "channel": channel,
                    "normalized_value": normalized_value,
                },
            )
        )
        .mappings()
        .one()
    )


async def lock_contact(
    session: AsyncSession, organization_id: UUID, principal_id: UUID, contact_id: UUID
) -> RowMapping:
    """Row-lock the principal's own contact or raise the typed not-found."""
    row = (
        (await session.execute(_LOCK_SQL, _keyed(organization_id, principal_id, contact_id)))
        .mappings()
        .first()
    )
    if row is None:
        raise PrincipalContactNotFound(principal_id, contact_id)
    return row


async def set_pending_verification(
    session: AsyncSession,
    organization_id: UUID,
    principal_id: UUID,
    contact_id: UUID,
    hashed_code: str,
    expires_at: datetime,
) -> None:
    await session.execute(
        _SET_PENDING_SQL,
        {
            **_keyed(organization_id, principal_id, contact_id),
            "code_hash": hashed_code,
            "expires_at": expires_at,
        },
    )


async def mark_verified(
    session: AsyncSession, organization_id: UUID, principal_id: UUID, contact_id: UUID
) -> None:
    await session.execute(_MARK_VERIFIED_SQL, _keyed(organization_id, principal_id, contact_id))


async def bump_attempts(
    session: AsyncSession, organization_id: UUID, principal_id: UUID, contact_id: UUID
) -> int:
    row = (
        await session.execute(_BUMP_ATTEMPTS_SQL, _keyed(organization_id, principal_id, contact_id))
    ).one()
    return int(row[0])
