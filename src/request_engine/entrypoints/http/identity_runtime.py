from request_engine.platform.db.identity_binding_reader import PostgresIdentityBindingReader
from request_engine.platform.db.platform_principal_authority_reader import (
    PostgresPlatformPrincipalAuthorityReader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.tenant_principal_authority_reader import (
    PostgresTenantPrincipalAuthorityReader,
)
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver


def build_identity_principal_resolver(session_factory: SessionFactory) -> IdentityPrincipalResolver:
    """Compose RE-owned IdentityBinding and Principal-authority materialization."""

    return IdentityPrincipalResolver(
        binding_reader=PostgresIdentityBindingReader(session_factory),
        tenant_authority_reader=PostgresTenantPrincipalAuthorityReader(session_factory),
        platform_authority_reader=PostgresPlatformPrincipalAuthorityReader(session_factory),
    )
