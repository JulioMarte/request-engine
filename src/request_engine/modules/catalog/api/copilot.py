from request_engine.modules.catalog.adapters.db.copilot_reader import PostgresCopilotCatalogReader
from request_engine.modules.catalog.contracts.copilot import CopilotCatalogReader
from request_engine.platform.db.session import SessionFactory


def build_copilot_catalog_reader(session_factory: SessionFactory) -> CopilotCatalogReader:
    return PostgresCopilotCatalogReader(session_factory)
