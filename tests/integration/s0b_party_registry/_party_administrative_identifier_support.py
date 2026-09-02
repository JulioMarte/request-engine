from uuid import UUID, uuid4

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_reader import (
    PostgresPartyAdministrativeIdentifierReader,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_administrative_identifier as admin_identifier_commands,
)
from request_engine.modules.tenancy.application.queries.party_administrative_identifiers import (
    PartyAdministrativeIdentifierLookupQuery,
    lookup_party_by_administrative_identifier,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind


def identifier_command(
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    *,
    value: str = "MEM-001 23",
    idempotency_key: str | None = None,
) -> admin_identifier_commands.AddPartyAdministrativeIdentifierCommand:
    return admin_identifier_commands.AddPartyAdministrativeIdentifierCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        kind="insurance_member",
        issuer=" ARS   Primera ",
        value=value,
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key=idempotency_key or f"insurance-{uuid4().hex}",
        platform="reception_web",
    )


async def lookup_ids(
    reader: PostgresPartyAdministrativeIdentifierReader,
    organization_id: UUID,
    value: str = "MEM-00123",
) -> list[UUID]:
    parties = await lookup_party_by_administrative_identifier(
        reader,
        PartyAdministrativeIdentifierLookupQuery(
            organization_id=organization_id,
            kind="insurance_member",
            issuer="ars primera",
            value=value,
        ),
    )
    return [party.party_id for party in parties]
