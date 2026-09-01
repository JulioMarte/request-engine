"""Command-row builders for party registry insert statements."""

from uuid import UUID

from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.add_party_document import (
    AddPartyDocumentCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredVia


def _verified_for(registered_via: RegisteredVia) -> bool:
    return registered_via is RegisteredVia.OPERATOR


def contact_point_rows(
    command: RegisterPartyCommand,
    party_id: UUID,
) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": party_id,
            "channel": contact.channel,
            "normalized_value": contact.value,
            "verified": _verified_for(command.registered_via),
            "registered_via": command.registered_via.value,
            "principal_id": command.principal_id,
        }
        for contact in command.contact_points
    ]


def single_contact_point_row(
    command: AddPartyContactPointCommand,
) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": command.party_id,
            "channel": command.channel,
            "normalized_value": command.value,
            "verified": _verified_for(command.registered_via),
            "registered_via": command.registered_via.value,
            "principal_id": command.principal_id,
        }
    ]


def single_document_row(command: AddPartyDocumentCommand) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": command.party_id,
            "kind": command.kind,
            "normalized_value": command.value,
            "principal_id": command.principal_id,
        }
    ]


def document_rows(command: RegisterPartyCommand, party_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": party_id,
            "kind": document.kind,
            "normalized_value": document.value,
            "principal_id": command.principal_id,
        }
        for document in command.documents
    ]
