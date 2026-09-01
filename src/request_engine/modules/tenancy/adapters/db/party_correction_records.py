"""Audit and revision-ledger record keeping for the party registry corrections.

Every correction/rollback closes its transaction the same way: one §9.3
revision-ledger append with the post-mutation identity snapshot, one audit
append carrying the §9.1 attribution facts (source_kind, platform, relay
principal) and the idempotency completion with the serialized party state.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_correction_support import (
    CorrectionCommand,
    party_state,
)
from request_engine.modules.tenancy.adapters.db.party_registry_codec import party_to_json
from request_engine.modules.tenancy.adapters.db.party_registry_rows import audit_attribution
from request_engine.modules.tenancy.adapters.db.party_revision_ledger import record_party_revision
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.idempotency.postgres import complete_idempotency

_CHANGE_KINDS = {
    "parties.rename": "renamed",
    "parties.add_document": "document_added",
    "parties.deactivate_contact_point": "contact_deactivated",
    "parties.deactivate": "party_deactivated",
    "parties.rollback_identity": "rollback",
}


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
        details={**details, **audit_attribution(command)},
    )


async def record_correction_revision(
    session: AsyncSession, command: CorrectionCommand, capability: str
) -> None:
    """Append the §9.3 revision for one correction/rollback capability."""
    await record_party_revision(
        session,
        command=command,
        organization_id=command.organization_id,
        party_id=command.party_id,
        change_kind=_CHANGE_KINDS[capability],
    )


async def finish_party_state(
    session: AsyncSession,
    command: CorrectionCommand,
    capability: str,
    idempotency_id: UUID,
    details: dict[str, object],
) -> RegisteredParty:
    """Record the revision, snapshot the party, audit and complete the replay."""
    await record_correction_revision(session, command, capability)
    state = await party_state(session, command.organization_id, command.party_id)
    await audit_correction(session, command, capability, idempotency_id, details)
    await complete_idempotency(session, idempotency_id, {"party": party_to_json(state)})
    return state
