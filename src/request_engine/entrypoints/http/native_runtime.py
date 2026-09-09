from dataclasses import dataclass

from request_engine.entrypoints.http.security import build_identity_principal_resolver
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.workload_credential_reader import PostgresWorkloadCredentialReader
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver
from request_engine.platform.security.native_http import NativeSessionHttpSubjectResolver
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator
from request_engine.platform.security.subject_http import ProviderNeutralHttpActorResolver
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


def build_native_auth_runtime(session_factory: SessionFactory) -> NativeAuthRuntime:
    """Build the providerless HUMAN + workload runtime without an external IdP."""

    store = PostgresNativeHumanAuthStore(session_factory)
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(session_factory)
    )
    workload_authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(session_factory)
    )
    principal_resolver = build_identity_principal_resolver(session_factory)
    subject_resolver = DispatchedBearerSubjectResolver(
        native_subject_resolver=NativeSessionHttpSubjectResolver(authenticator),
        workload_authenticator=workload_authenticator,
        workload_credential_reader=PostgresWorkloadCredentialReader(session_factory),
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
    )
