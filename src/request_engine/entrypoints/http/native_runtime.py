from dataclasses import dataclass

from request_engine.entrypoints.http.security import build_identity_principal_resolver
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.oidc_authority_reader import PostgresOidcAuthorityReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.workload_credential_reader import PostgresWorkloadCredentialReader
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver
from request_engine.platform.security.native_http import NativeSessionHttpSubjectResolver
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator
from request_engine.platform.security.oidc_auth import JwksFetcher
from request_engine.platform.security.oidc_http import OidcHttpSubjectResolver
from request_engine.platform.security.subject_http import (
    ProviderNeutralHttpActorResolver,
    ProviderNeutralPlatformHttpActorResolver,
)
from request_engine.platform.security.workload_auth import WorkloadCredentialAuthenticator
from request_engine.platform.security.workload_http import DispatchedBearerSubjectResolver


@dataclass(frozen=True, slots=True)
class NativeAuthRuntime:
    """Providerless HUMAN and workload trust path composed from RE-owned boundaries.

    One bearer namespace dispatches deterministically between native human
    sessions and first-party workload credentials. Both paths emit identity
    only; every protected request still re-reads its IdentityBinding and
    current Principal authority before an ActorContext can be materialized.
    """

    service: NativeHumanAuthService
    authenticator: NativeSessionAuthenticator
    workload_authenticator: WorkloadCredentialAuthenticator
    actor_resolver: ProviderNeutralHttpActorResolver
    principal_resolver: IdentityPrincipalResolver
    platform_actor_resolver: ProviderNeutralPlatformHttpActorResolver | None


@dataclass(frozen=True, slots=True)
class OidcAuthRuntime:
    """Optional externally federated HUMAN authentication arm.

    Composing it adds JWT bearer dispatch to the native runtime; omitting it
    leaves the deployment byte-identical to the providerless composition.
    """

    subject_resolver: OidcHttpSubjectResolver


def build_native_auth_runtime(
    session_factory: SessionFactory,
    *,
    oidc_runtime: OidcAuthRuntime | None = None,
    platform_session_factory: SessionFactory | None = None,
) -> NativeAuthRuntime:
    """Build the providerless HUMAN + workload runtime without an external IdP.

    When ``oidc_runtime`` is provided, JWT-shaped bearers additionally dispatch
    to the federated OIDC arm; without it the runtime is unchanged.
    Platform HTTP materialization is opt-in and requires a separate connection
    with explicit permission to the private platform authority read function.
    The normal app connection never gains platform-control privileges.
    """

    store = PostgresNativeHumanAuthStore(session_factory)
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(session_factory)
    )
    workload_authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(session_factory)
    )
    principal_resolver = build_identity_principal_resolver(
        session_factory, platform_session_factory=platform_session_factory
    )
    subject_resolver = DispatchedBearerSubjectResolver(
        native_subject_resolver=NativeSessionHttpSubjectResolver(authenticator),
        workload_authenticator=workload_authenticator,
        workload_credential_reader=PostgresWorkloadCredentialReader(session_factory),
        oidc_subject_resolver=(None if oidc_runtime is None else oidc_runtime.subject_resolver),
    )
    return NativeAuthRuntime(
        service=NativeHumanAuthService(store=store),
        authenticator=authenticator,
        workload_authenticator=workload_authenticator,
        actor_resolver=ProviderNeutralHttpActorResolver(
            subject_resolver=subject_resolver,
            principal_resolver=principal_resolver,
        ),
        principal_resolver=principal_resolver,
        platform_actor_resolver=(
            None
            if platform_session_factory is None
            else ProviderNeutralPlatformHttpActorResolver(
                subject_resolver=subject_resolver,
                principal_resolver=principal_resolver,
            )
        ),
    )


async def build_oidc_subject_resolver(
    session_factory: SessionFactory,
    *,
    jwks_fetcher: JwksFetcher | None = None,
) -> OidcHttpSubjectResolver:
    """Compose the OIDC arm from the active authorities persisted in PostgreSQL.

    Construction performs no database or provider I/O. Every request reads
    current active configuration. Close the returned resolver at shutdown;
    injected fetchers remain caller-owned. A synchronous production factory
    can construct OidcHttpSubjectResolver with the same keyword arguments.
    """

    return OidcHttpSubjectResolver(
        authority_reader=PostgresOidcAuthorityReader(session_factory),
        jwks_fetcher=jwks_fetcher,
    )


__all__ = [
    "OidcAuthRuntime",
    "build_native_auth_runtime",
    "build_oidc_subject_resolver",
]
