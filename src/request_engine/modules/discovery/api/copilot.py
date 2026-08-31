from request_engine.modules.discovery.adapters.db.copilot_reader import (
    PostgresCopilotDiscoveryPublicationReader,
)
from request_engine.modules.discovery.contracts.copilot import CopilotDiscoveryPublicationReader
from request_engine.platform.db.session import SessionFactory


def build_copilot_discovery_reader(
    session_factory: SessionFactory,
) -> CopilotDiscoveryPublicationReader:
    return PostgresCopilotDiscoveryPublicationReader(session_factory)
