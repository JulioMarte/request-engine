"""PostgreSQL `parties.rollback_identity` command adapter (docs/v3/38 §9.3).

Rollback applies a prior revision's recorded snapshot as a NEW ledger
revision: history is never rewritten. It is allowed on inactive Parties
(that is its main use). The party row is locked first, so the target
revision is validated against the current cursor under serialization. One
Session, one tenant transaction, standard idempotency replay, audited; no
outbox events.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_correction_records import (
    audit_correction,
    record_correction_revision,
)
from request_engine.modules.tenancy.adapters.db.party_correction_support import (
    fetch_one,
    lock_any_party,
    party_state,
    run_correction,
)
from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_to_json
from request_engine.modules.tenancy.adapters.db.party_registry_correction_codec import replay_party
from request_engine.modules.tenancy.adapters.db.party_rollback_restore import restore_snapshot
from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
)
from request_engine.modules.tenancy.application.errors import (
    PartyRevisionNotFound,
    PartyRevisionTargetInvalid,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.postgres import (
    command_fingerprint,
    complete_idempotency,
)

_ROLLBACK_CAPABILITY = "parties.rollback_identity"

_CURRENT_REVISION_SQL = text(
    "SELECT identity_revision FROM request_engine.parties"
    " WHERE organization_id = :organization_id AND id = :party_id"
)

_TARGET_REVISION_SQL = text(
    "SELECT revision, state FROM request_engine.party_identity_revisions"
    " WHERE organization_id = :organization_id AND party_id = :party_id"
    " AND revision = :target_revision"
)


class PostgresPartyRollbackCommands:
    """Operator-granted identity rollback with idempotent replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def rollback_party_identity(
        self, command: RollbackPartyIdentityCommand
    ) -> RegisteredParty:
        fingerprint = command_fingerprint(
            _ROLLBACK_CAPABILITY,
            {"party_id": str(command.party_id), "target_revision": command.target_revision},
        )
        return await run_correction(
            self._session_factory,
            command,
            _ROLLBACK_CAPABILITY,
            fingerprint,
            replay_party,
            lambda session, idempotency_id: _rollback(session, command, idempotency_id),
        )


async def _rollback(
    session: AsyncSession, command: RollbackPartyIdentityCommand, idempotency_id: UUID
) -> RegisteredParty:
    await lock_any_party(session, command.organization_id, command.party_id)
    current = await _current_revision(session, command)
    if command.target_revision > current:
        raise PartyRevisionTargetInvalid(command.party_id, command.target_revision, current)
    target = await fetch_one(
        session,
        _TARGET_REVISION_SQL,
        {
            "organization_id": command.organization_id,
            "party_id": command.party_id,
            "target_revision": command.target_revision,
        },
    )
    if target is None:
        raise PartyRevisionNotFound(command.party_id, command.target_revision)
    await restore_snapshot(session, command.organization_id, command.party_id, target["state"])
    await record_correction_revision(session, command, _ROLLBACK_CAPABILITY)
    state = await party_state(session, command.organization_id, command.party_id)
    await audit_correction(
        session,
        command,
        _ROLLBACK_CAPABILITY,
        idempotency_id,
        {"target_revision": command.target_revision},
    )
    await complete_idempotency(
        session,
        idempotency_id,
        {"party": party_to_json(state), "target_revision": command.target_revision},
    )
    return state


async def _current_revision(session: AsyncSession, command: RollbackPartyIdentityCommand) -> int:
    row = await fetch_one(
        session,
        _CURRENT_REVISION_SQL,
        {"organization_id": command.organization_id, "party_id": command.party_id},
    )
    if row is None:
        raise PartyRevisionNotFound(command.party_id, command.target_revision)
    return cast(int, row["identity_revision"])
