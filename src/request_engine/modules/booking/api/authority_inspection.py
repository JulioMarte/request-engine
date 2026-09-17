from request_engine.modules.booking.adapters.db.resource_authority_inspector import (
    PostgresResourceAuthorityInspector,
)
from request_engine.modules.tenancy.contracts.resource_authority import ResourceAuthorityInspector
from request_engine.platform.db.session import SessionFactory


def build_resource_authority_inspector(
    session_factory: SessionFactory,
) -> ResourceAuthorityInspector:
    return PostgresResourceAuthorityInspector(session_factory)
