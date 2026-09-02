"""Shared in-transaction persistence for creation of a normal tenant-owned Party."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_registry_rows import (
    attribution_values,
    contact_point_rows,
    document_rows,
)
from request_engine.modules.tenancy.adapters.db.party_registry_store import (
    insert_contact_points,
    insert_documents,
    insert_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_views import load_party_views
from request_engine.modules.tenancy.adapters.db.party_revision_ledger import record_party_revision
from request_engine.modules.tenancy.application.commands.register_party import RegisterPartyCommand
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.outbox.postgres import append_outbox


async def write_registered_party(
    session: AsyncSession,
    command: RegisterPartyCommand,
    *,
    command_name: str,
    idempotency_id: UUID,
    audit_details: dict[str, object] | None = None,
) -> RegisteredParty:
    """Write Party/contact/document facts and standard registration audit/outbox state."""

    party_id = await insert_party(
        session,
        organization_id=command.organization_id,
        party_kind=command.party_kind.value,
        display_name=command.display_name,
        principal_id=command.principal_id,
        attribution=attribution_values(command),
    )
    await insert_contact_points(session, contact_point_rows(command, party_id))
    await insert_documents(session, document_rows(command, party_id))
    await record_party_revision(
        session,
        command=command,
        organization_id=command.organization_id,
        party_id=party_id,
        change_kind="registered",
    )
    state = (await load_party_views(session, command.organization_id, [party_id]))[0]
    details: dict[str, object] = {
        "party_kind": command.party_kind.value,
        "display_name": command.display_name,
        **attribution_values(command),
        "contact_point_count": len(state.contact_points),
        "document_count": len(state.documents),
    }
    if audit_details:
        details.update(audit_details)
    await append_audit(
        session,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        command_name=command_name,
        aggregate_kind="Party",
        aggregate_id=party_id,
        idempotency_id=idempotency_id,
        details=details,
    )
    await append_outbox(
        session,
        organization_id=command.organization_id,
        event_type="party.registered.v1",
        aggregate_kind="Party",
        aggregate_id=party_id,
        payload={
            "party_id": str(party_id),
            "display_name": command.display_name,
            "contact_point_count": len(state.contact_points),
        },
    )
    return state
