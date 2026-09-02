"""SQL and command parameter builders for Party administrative identifiers."""

from sqlalchemy import text

from request_engine.modules.tenancy.adapters.db.party_registry_rows import attribution_values
from request_engine.modules.tenancy.application.commands.add_party_administrative_identifier import (
    AddPartyAdministrativeIdentifierCommand,
)

INSERT_IDENTIFIER = text(
    """
    INSERT INTO request_engine.party_administrative_identifiers (
        organization_id, party_id, kind, issuer, normalized_issuer, value, normalized_value,
        created_by_principal_id, source_kind, platform, relay_principal_id
    ) VALUES (
        :organization_id, :party_id, :kind, :issuer, :normalized_issuer, :value,
        :normalized_value, :principal_id, :source_kind, :platform, :relay_principal_id
    )
    ON CONFLICT DO NOTHING
    RETURNING id, party_id, kind, issuer, normalized_issuer, value, normalized_value, active
    """
)

FIND_IDENTIFIER = text(
    """
    SELECT id, party_id, kind, issuer, normalized_issuer, value, normalized_value, active
    FROM request_engine.party_administrative_identifiers
    WHERE organization_id = :organization_id
      AND kind = :kind
      AND normalized_issuer = :normalized_issuer
      AND active
      AND (normalized_value = :normalized_value OR party_id = :party_id)
    ORDER BY (normalized_value = :normalized_value) DESC
    LIMIT 1
    """
)


def fingerprint_values(command: AddPartyAdministrativeIdentifierCommand) -> dict[str, object]:
    return {
        "party_id": str(command.party_id),
        "kind": command.kind,
        "issuer": command.issuer,
        "normalized_issuer": command.normalized_issuer,
        "value": command.value,
        "normalized_value": command.normalized_value,
        "source_kind": command.source_kind.value,
        "platform": command.platform,
    }


def sql_values(command: AddPartyAdministrativeIdentifierCommand) -> dict[str, object]:
    return {
        "organization_id": command.organization_id,
        "party_id": command.party_id,
        "principal_id": command.principal_id,
        "kind": command.kind,
        "issuer": command.issuer,
        "normalized_issuer": command.normalized_issuer,
        "value": command.value,
        "normalized_value": command.normalized_value,
        **attribution_values(command),
    }
