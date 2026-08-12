from request_engine.modules.tenancy.adapters.db.party_authority_reader import (
    PostgresPartyAuthorityReader,
)
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.db.session import SessionFactory


def build_party_authority_reader(session_factory: SessionFactory) -> PartyAuthorityReader:
    """Compose the tenant-owned Party authority reader behind the module API surface."""

    return PostgresPartyAuthorityReader(session_factory)
