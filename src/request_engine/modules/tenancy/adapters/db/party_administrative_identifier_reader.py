"""Tenant-scoped reader for Party administrative identifiers."""

from sqlalchemy import text

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_codec import (
    identifier_from_mapping,
)
from request_engine.modules.tenancy.adapters.db.party_registry_views import load_party_views
from request_engine.modules.tenancy.application.queries.party_administrative_identifiers import (
    PartyAdministrativeIdentifierListQuery,
    PartyAdministrativeIdentifierLookupQuery,
)
from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifier,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_LIST = text("""
SELECT id, party_id, kind, issuer, normalized_issuer, value, normalized_value, active
FROM request_engine.party_administrative_identifiers
WHERE organization_id = :organization_id AND party_id = :party_id AND active
ORDER BY kind, normalized_issuer, normalized_value, id
""")
_LOOKUP = text("""
SELECT party_id
FROM request_engine.party_administrative_identifiers
WHERE organization_id = :organization_id AND kind = :kind
  AND normalized_issuer = :issuer AND normalized_value = :value AND active
LIMIT 1
""")


class PostgresPartyAdministrativeIdentifierReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def list_for_party(
        self, query: PartyAdministrativeIdentifierListQuery
    ) -> tuple[PartyAdministrativeIdentifier, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            result = await session.execute(
                _LIST,
                {"organization_id": query.organization_id, "party_id": query.party_id},
            )
            return tuple(identifier_from_mapping(row) for row in result.mappings().all())

    async def lookup_party(
        self, query: PartyAdministrativeIdentifierLookupQuery
    ) -> tuple[RegisteredParty, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            result = await session.execute(
                _LOOKUP,
                {
                    "organization_id": query.organization_id,
                    "kind": query.kind,
                    "issuer": query.issuer,
                    "value": query.value,
                },
            )
            party_id = result.scalar_one_or_none()
            if party_id is None:
                return ()
            return tuple(await load_party_views(session, query.organization_id, [party_id]))
