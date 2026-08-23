from dataclasses import dataclass

from request_engine.modules.discovery.adapters.db.candidate_reader import (
    PostgresDiscoveryCandidateReader,
)
from request_engine.modules.discovery.adapters.db.handoff_issuer import (
    PostgresDiscoveryHandoffIssuer,
)
from request_engine.modules.discovery.application.handoff import DiscoveryHandoffIssuer
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidateReader,
)
from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class DiscoveryDatabasePorts:
    candidate_reader: DiscoveryCandidateReader
    handoff_issuer: DiscoveryHandoffIssuer


def build_discovery_database_ports(
    discovery_session_factory: SessionFactory,
) -> DiscoveryDatabasePorts:
    """Build ports for a credential inheriting only request_engine_discovery.

    The caller must not pass the tenant-domain request_engine_app factory here.
    PostgreSQL privilege evidence verifies the expected runtime role separately.
    """

    return DiscoveryDatabasePorts(
        candidate_reader=PostgresDiscoveryCandidateReader(discovery_session_factory),
        handoff_issuer=PostgresDiscoveryHandoffIssuer(discovery_session_factory),
    )
