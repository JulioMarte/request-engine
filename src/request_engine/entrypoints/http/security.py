from request_engine.platform.db.identity_binding_reader import PostgresIdentityBindingReader
from request_engine.platform.db.platform_principal_authority_reader import (
    PostgresPlatformPrincipalAuthorityReader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.tenant_principal_authority_reader import (
    PostgresTenantPrincipalAuthorityReader,
)
from request_engine.platform.security.http import ActorResolver, AuthenticationRequired
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver


def build_identity_principal_resolver(
    session_factory: SessionFactory,
    *,
    platform_session_factory: SessionFactory | None = None,
) -> IdentityPrincipalResolver:
    """Compose RE-owned IdentityBinding and Principal-authority materialization."""

    return IdentityPrincipalResolver(
        binding_reader=PostgresIdentityBindingReader(session_factory),
        tenant_authority_reader=PostgresTenantPrincipalAuthorityReader(session_factory),
        platform_authority_reader=PostgresPlatformPrincipalAuthorityReader(
            platform_session_factory if platform_session_factory is not None else session_factory
        ),
    )


__all__ = [
    "ActorResolver",
    "AuthenticationRequired",
    "build_identity_principal_resolver",
]
