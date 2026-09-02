"""Idempotency fingerprint builders for the party registry command adapters."""

from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import RegisterPartyCommand


def register_fingerprint(command: RegisterPartyCommand) -> dict[str, object]:
    return {
        "display_name": command.display_name,
        "source_kind": command.source_kind.value,
        "platform": command.platform,
        "contact_points": [
            {"channel": c.channel, "normalized_value": c.value} for c in command.contact_points
        ],
        "documents": [
            {
                "kind": d.kind,
                "authority": d.authority,
                "normalized_value": d.value,
            }
            for d in command.documents
        ],
    }


def add_fingerprint(command: AddPartyContactPointCommand) -> dict[str, object]:
    return {
        "party_id": str(command.party_id),
        "channel": command.channel,
        "normalized_value": command.value,
        "source_kind": command.source_kind.value,
        "platform": command.platform,
    }
