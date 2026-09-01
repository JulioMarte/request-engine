"""Shared transaction plumbing for the party registry correction commands.

Every correction runs one Session and one tenant transaction: standard
idempotency acquire/replay, a row-locked party existence check, an audit
append and the idempotency completion. No correction emits outbox events.
"""

from collections.abc import Awaitable, Callable
from typing import Never, Protocol
from uuid import UUID

from sqlalchemy import Executable, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_to_json
from request_engine.modules.tenancy.adapters.db.party_registry_views import load_party_views
from request_engine.modules.tenancy.application.errors import PartyNotFound
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)

_LOCK_ANY_PARTY_SQL = text(
    "SELECT active FROM request_engine.parties"
    " WHERE organization_id = :organization_id AND id = :party_id FOR UPDATE"
)


class CorrectionCommand(Protocol):
    @property
    def organization_id(self) -> UUID: ...

    @property
    def principal_id(self) -> UUID: ...

    @property
    def party_id(self) -> UUID: ...

    @property
    def idempotency_key(self) -> str: ...


async def fetch_one(
    session: AsyncSession, statement: Executable, params: dict[str, object]
) -> RowMapping | None:
    return (await session.execute(statement, params)).mappings().first()


async def lock_any_party(session: AsyncSession, organization_id: UUID, party_id: UUID) -> None:
    """Row-lock the party; only existence is required (deactivate is idempotent)."""

    locked = await fetch_one(
        session, _LOCK_ANY_PARTY_SQL, {"organization_id": organization_id, "party_id": party_id}
    )
    if locked is None:
        raise PartyNotFound(party_id)


async def party_state(
    session: AsyncSession, organization_id: UUID, party_id: UUID
) -> RegisteredParty:
    return (await load_party_views(session, organization_id, [party_id]))[0]


async def audit_correction(
    session: AsyncSession,
    command: CorrectionCommand,
    capability: str,
    idempotency_id: UUID,
    details: dict[str, object],
) -> None:
    await append_audit(
        session,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        command_name=capability,
        aggregate_kind="Party",
        aggregate_id=command.party_id,
        idempotency_id=idempotency_id,
        details=details,
    )


async def finish_party_state(
    session: AsyncSession,
    command: CorrectionCommand,
    capability: str,
    idempotency_id: UUID,
    details: dict[str, object],
) -> RegisteredParty:
    """Snapshot the party, append the audit record and complete the replay."""

    state = await party_state(session, command.organization_id, command.party_id)
    await audit_correction(session, command, capability, idempotency_id, details)
    await complete_idempotency(session, idempotency_id, {"party": party_to_json(state)})
    return state


async def run_correction[V](
    session_factory: SessionFactory,
    command: CorrectionCommand,
    capability: str,
    fingerprint: str,
    replay: Callable[[dict[str, object]], V],
    mutate: Callable[[AsyncSession, UUID], Awaitable[V]],
    on_conflict: Callable[[IntegrityError], Awaitable[Never]] | None = None,
) -> V:
    """Run one idempotent correction transaction and map its typed conflict."""

    try:
        async with tenant_transaction(session_factory, command.organization_id) as session:
            idempotency_id, replay_data = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay_data is not None:
                return replay(replay_data)
            return await mutate(session, idempotency_id)
    except IntegrityError as exc:
        if on_conflict is not None:
            await on_conflict(exc)
        raise exc
