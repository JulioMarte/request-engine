from dataclasses import dataclass

from request_engine.entrypoints.http.identity_runtime import build_identity_principal_resolver
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver
from request_engine.platform.security.native_http import NativeSessionHttpActorResolver
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator


@dataclass(frozen=True, slots=True)
class NativeHumanRuntime:
    """Providerless HUMAN trust path composed from RE-owned PostgreSQL boundaries."""

    service: NativeHumanAuthService
    authenticator: NativeSessionAuthenticator
    actor_resolver: NativeSessionHttpActorResolver
    principal_resolver: IdentityPrincipalResolver


def build_native_human_runtime(session_factory: SessionFactory) -> NativeHumanRuntime:
    """Build one coherent Native HUMAN runtime without an external identity provider.

    Credential verification is intentionally separate from business authority. A
    successful Native session only produces an AuthenticatedSubject; every
    protected request still re-reads its IdentityBinding and current Principal
    authority before an ActorContext can be materialized.
    """

    store = PostgresNativeHumanAuthStore(session_factory)
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(session_factory)
    )
    principal_resolver = build_identity_principal_resolver(session_factory)
    return NativeHumanRuntime(
        service=NativeHumanAuthService(store=store),
        authenticator=authenticator,
        actor_resolver=NativeSessionHttpActorResolver(
            authenticator=authenticator,
            principal_resolver=principal_resolver,
        ),
        principal_resolver=principal_resolver,
    )
