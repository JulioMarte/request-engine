"""PostgreSQL `parties.deactivate_contact_point` and `parties.deactivate`.

Operator-granted deactivations. `parties.deactivate_contact_point` flips one
contact point's `active` to false and never touches `verified`, so the
verification monotonicity guard (I-S0b-4) cannot trip. `parties.deactivate`
retires a Party from every lookup mode and is idempotent on an already
inactive Party. One Session, one tenant transaction, idempotent replay,
audited; no outbox events.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_correction_support import (
    audit_correction,
    fetch_one,
    finish_party_state,
    lock_any_party,
    party_state,
    record_correction_revision,
    run_correction,
)
from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_to_json
from request_engine.modules.tenancy.adapters.db.party_registry_correction_codec import (
    contact_point_from_row,
    contact_point_to_json,
    replay_contact_point,
    replay_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_store import lock_party
from request_engine.modules.tenancy.application.commands import (
    deactivate_party,
    deactivate_party_contact_point,
)
from request_engine.modules.tenancy.application.errors import PartyContactPointNotFound
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    RegisteredParty,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.postgres import command_fingerprint, complete_idempotency

_CONTACT_POINT_CAPABILITY = "parties.deactivate_contact_point"
_PARTY_CAPABILITY = "parties.deactivate"

_DEACTIVATE_CONTACT_POINT_SQL = text(
    "UPDATE request_engine.party_contact_points"
    " SET active = false, updated_at = clock_timestamp()"
    " WHERE organization_id = :organization_id AND id = :contact_point_id"
    " AND party_id = :party_id"
    " RETURNING id, party_id, channel, normalized_value, verified, source_kind"
)

_DEACTIVATE_PARTY_SQL = text(
    "UPDATE request_engine.parties"
    " SET active = false, updated_at = clock_timestamp()"
    " WHERE organization_id = :organization_id AND id = :party_id"
)


class PostgresPartyDeactivationCommands:
    """Operator-granted contact-point and party deactivation with replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def deactivate_party_contact_point(
        self, command: deactivate_party_contact_point.DeactivatePartyContactPointCommand
    ) -> PartyContactPoint:
        fingerprint = command_fingerprint(
            _CONTACT_POINT_CAPABILITY,
            {"party_id": command.party_id, "contact_point_id": command.contact_point_id},
        )

        async def mutate(session: AsyncSession, idempotency_id: UUID) -> PartyContactPoint:
            await lock_party(session, command.organization_id, command.party_id)
            updated = await fetch_one(
                session,
                _DEACTIVATE_CONTACT_POINT_SQL,
                {
                    "organization_id": command.organization_id,
                    "party_id": command.party_id,
                    "contact_point_id": command.contact_point_id,
                },
            )
            if updated is None:
                raise PartyContactPointNotFound(command.party_id, command.contact_point_id)
            affected = contact_point_from_row(updated)
            await record_correction_revision(session, command, _CONTACT_POINT_CAPABILITY)
            state = await party_state(session, command.organization_id, command.party_id)
            payload: dict[str, object] = {
                "party": party_to_json(state),
                "contact_point": contact_point_to_json(affected),
            }
            await audit_correction(session, command, _CONTACT_POINT_CAPABILITY, idempotency_id, {})
            await complete_idempotency(session, idempotency_id, payload)
            return affected

        return await run_correction(
            self._session_factory,
            command,
            _CONTACT_POINT_CAPABILITY,
            fingerprint,
            lambda data: replay_contact_point(data, command.party_id, command.contact_point_id),
            mutate,
        )

    async def deactivate_party(
        self, command: deactivate_party.DeactivatePartyCommand
    ) -> RegisteredParty:
        fingerprint = command_fingerprint(_PARTY_CAPABILITY, {"party_id": command.party_id})

        async def mutate(session: AsyncSession, idempotency_id: UUID) -> RegisteredParty:
            await lock_any_party(session, command.organization_id, command.party_id)
            await session.execute(
                _DEACTIVATE_PARTY_SQL,
                {"organization_id": command.organization_id, "party_id": command.party_id},
            )
            return await finish_party_state(session, command, _PARTY_CAPABILITY, idempotency_id, {})

        return await run_correction(
            self._session_factory, command, _PARTY_CAPABILITY, fingerprint, replay_party, mutate
        )
