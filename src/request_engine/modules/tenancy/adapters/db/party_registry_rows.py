"""Command-row builders and attribution values for party registry writes."""

from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.add_party_document import (
    AddPartyDocumentCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import RegisterPartyCommand
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind


class AttributedCommand(Protocol):
    @property
    def organization_id(self) -> UUID: ...

    @property
    def principal_id(self) -> UUID: ...

    @property
    def source_kind(self) -> PartySourceKind | None: ...

    @property
    def platform(self) -> str | None: ...

    @property
    def technical_principal_id(self) -> UUID | None: ...


def relayed_operator(command: AttributedCommand) -> bool:
    return (
        command.source_kind is PartySourceKind.OPERATOR
        and command.technical_principal_id is not None
        and command.technical_principal_id != command.principal_id
    )


def attribution_values(command: AttributedCommand) -> dict[str, object]:
    return {
        "source_kind": command.source_kind.value if command.source_kind else None,
        "platform": command.platform,
        "relay_principal_id": (
            command.technical_principal_id if relayed_operator(command) else None
        ),
    }


def ledger_attribution(command: AttributedCommand) -> dict[str, object]:
    relayed = relayed_operator(command)
    return {
        "actor_principal_id": (command.technical_principal_id if relayed else command.principal_id),
        "attributed_operator_principal_id": command.principal_id if relayed else None,
    }


def audit_attribution(command: AttributedCommand) -> dict[str, object]:
    return {
        "source_kind": command.source_kind.value if command.source_kind else None,
        "platform": command.platform,
        "relay_principal_id": (
            command.technical_principal_id if relayed_operator(command) else None
        ),
    }


def contact_point_rows(command: RegisterPartyCommand, party_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": party_id,
            "channel": contact.channel,
            "normalized_value": contact.value,
            "verified": True,
            "principal_id": command.principal_id,
            **attribution_values(command),
        }
        for contact in command.contact_points
    ]


def single_contact_point_row(command: AddPartyContactPointCommand) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": command.party_id,
            "channel": command.channel,
            "normalized_value": command.value,
            "verified": True,
            "principal_id": command.principal_id,
            **attribution_values(command),
        }
    ]


def single_document_row(command: AddPartyDocumentCommand) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": command.party_id,
            "kind": command.kind,
            "authority": command.authority,
            "normalized_value": command.value,
            "principal_id": command.principal_id,
            **attribution_values(command),
        }
    ]


def document_rows(command: RegisterPartyCommand, party_id: UUID) -> list[dict[str, object]]:
    return [
        {
            "organization_id": command.organization_id,
            "party_id": party_id,
            "kind": document.kind,
            "authority": document.authority,
            "normalized_value": document.value,
            "principal_id": command.principal_id,
            **attribution_values(command),
        }
        for document in command.documents
    ]
