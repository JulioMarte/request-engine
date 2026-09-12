import os
from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import FastAPI, Request, Response

from request_engine.entrypoints.http.capabilities import create_capability_router
from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.entrypoints.http.module_composition import install_business_modules
from request_engine.entrypoints.http.native_auth import create_native_auth_router
from request_engine.entrypoints.http.native_runtime import (
    OidcAuthRuntime,
    build_native_auth_runtime,
)
from request_engine.entrypoints.http.operation_catalog import create_operation_catalog_router
from request_engine.entrypoints.http.operational_composition import install_operational_modules
from request_engine.entrypoints.http.operator_resolution import (
    DeploymentOperatorActorResolver,
    OperatorCapabilitySource,
)
from request_engine.entrypoints.http.security import build_identity_principal_resolver
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.modules.tenancy.api import build_principal_authority_reader
from request_engine.platform.db.agent_budget_enforcer import PostgresAgentBudgetEnforcer
from request_engine.platform.db.agent_policy_reader import PostgresAgentPolicyReader
from request_engine.platform.db.delegation_reader import PostgresDelegationReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.acting_operator import (
    ActingOperatorActorResolver,
    OperatorActorResolver,
)
from request_engine.platform.security.agent_policy_http import AgentPolicyActorResolver
from request_engine.platform.security.delegation_http import DelegatedAgentActorResolver
from request_engine.platform.security.discovery import (
    BaselineTenantCapabilityPolicy,
    TenantCapabilityPolicy,
)
from request_engine.platform.security.execution_context import clear_actor_context
from request_engine.platform.security.http import (
    ActorResolver,
    RequestExecutionActorResolver,
    TenantCapabilityActorResolver,
    request_correlation_id,
)
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator
from request_engine.platform.security.oidc_http import OidcHttpSubjectResolver
from request_engine.platform.security.subject_http import (
    HttpSubjectResolver,
    ProviderNeutralHttpActorResolver,
)

_APPOINTMENT_OPTION_SIGNING_KEY_ENV = "REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY"
_IDENTITY_EXCHANGE_KEY_ENV = "REQUEST_ENGINE_IDENTITY_EXCHANGE_KEY"
_CORRELATION_HEADER = "X-Correlation-ID"


async def _request_execution_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = request_correlation_id(request)
    try:
        response = await call_next(request)
        response.headers[_CORRELATION_HEADER] = str(correlation_id)
        return response
    finally:
        clear_actor_context()


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    slot_offer_ports: QueueSlotOfferHttpPorts | None = None,
    appointment_option_signing_key: bytes | None = None,
    identity_exchange_fingerprint_key: bytes | None = None,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
    operator_actor_resolver: OperatorActorResolver | None = None,
    operator_capability_source: OperatorCapabilitySource | None = None,
    native_auth_service: NativeHumanAuthService | None = None,
    native_session_authenticator: NativeSessionAuthenticator | None = None,
    native_identity_authority_id: UUID | None = None,
) -> FastAPI:
    """Compose the full single-app HTTP surface (business + operational configuration).

    This is the canonical composition root of Request Engine: business module
    surfaces, the operational configuration surfaces (/v1/operations/*, tenancy
    operational profile/contacts, discovery operational) and the operation
    catalog are all mounted on one app. Authorization is unchanged: capability
    metadata plus granular Representation grant/revoke decide who reaches what.
    The operational installers share the same execution actor resolver chain as
    the business modules, so acting-operator relay, tenant capability filtering
    and correlation binding apply identically.

    Production deployments should prefer create_native_app or
    create_authenticated_app so authentication evidence must pass through
    Request Engine-owned IdentityBinding and Principal-authority resolution.
    This lower-level seam remains temporarily for module/E2E composition while
    legacy tests are migrated away from capability-bearing fake resolvers.
    """

    signing_key = appointment_option_signing_key
    if signing_key is None:
        configured_key = os.environ.get(_APPOINTMENT_OPTION_SIGNING_KEY_ENV)
        if configured_key is None:
            raise RuntimeError(
                f"{_APPOINTMENT_OPTION_SIGNING_KEY_ENV} must be configured when no signing key "
                "is supplied explicitly"
            )
        signing_key = configured_key.encode("utf-8")
    identity_key = identity_exchange_fingerprint_key
    if identity_key is None:
        configured_identity_key = os.environ.get(_IDENTITY_EXCHANGE_KEY_ENV)
        if configured_identity_key is not None:
            identity_key = configured_identity_key.encode("utf-8")

    native_components = (
        native_auth_service,
        native_session_authenticator,
        native_identity_authority_id,
    )
    configured_native_components = sum(component is not None for component in native_components)
    if configured_native_components not in (0, len(native_components)):
        raise RuntimeError(
            "Native authentication requires service, session authenticator "
            "and authority id together"
        )

    policy = tenant_capability_policy or BaselineTenantCapabilityPolicy()
    operator_actors = operator_actor_resolver or DeploymentOperatorActorResolver(
        build_principal_authority_reader(session_factory), operator_capability_source
    )
    relay_actor_resolver = ActingOperatorActorResolver(actor_resolver, operator_actors)
    request_actor_resolver = RequestExecutionActorResolver(relay_actor_resolver)
    execution_actor_resolver = TenantCapabilityActorResolver(request_actor_resolver, policy)
    app = FastAPI(
        title="Request Engine",
        version="0.1.0",
        description=(
            "Headless customer-operations API. Supported production composition resolves "
            "authenticated subjects through Request Engine-owned identity and authority state."
        ),
    )
    app.middleware("http")(_request_execution_context)
    add_global_error_handlers(app)
    if (
        native_auth_service is not None
        and native_session_authenticator is not None
        and native_identity_authority_id is not None
    ):
        app.include_router(
            create_native_auth_router(
                service=native_auth_service,
                authenticator=native_session_authenticator,
                identity_authority_id=native_identity_authority_id,
            )
        )
    app.include_router(
        create_capability_router(
            actor_resolver=request_actor_resolver,
            tenant_capability_policy=policy,
        )
    )
    install_business_modules(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
        slot_offer_ports=slot_offer_ports,
        appointment_option_signing_key=signing_key,
        identity_exchange_fingerprint_key=identity_key,
    )
    install_operational_modules(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
    )
    app.include_router(create_operation_catalog_router(actor_resolver=execution_actor_resolver))
    return app


def create_authenticated_app(
    *,
    session_factory: SessionFactory,
    subject_resolver: HttpSubjectResolver,
    slot_offer_ports: QueueSlotOfferHttpPorts | None = None,
    appointment_option_signing_key: bytes | None = None,
    identity_exchange_fingerprint_key: bytes | None = None,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
    operator_actor_resolver: OperatorActorResolver | None = None,
    operator_capability_source: OperatorCapabilitySource | None = None,
) -> FastAPI:
    """Compose a provider-neutral deployment from authentication-only evidence."""

    actor_resolver = ProviderNeutralHttpActorResolver(
        subject_resolver=subject_resolver,
        principal_resolver=build_identity_principal_resolver(session_factory),
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        slot_offer_ports=slot_offer_ports,
        appointment_option_signing_key=appointment_option_signing_key,
        identity_exchange_fingerprint_key=identity_exchange_fingerprint_key,
        tenant_capability_policy=tenant_capability_policy,
        operator_actor_resolver=operator_actor_resolver,
        operator_capability_source=operator_capability_source,
    )


def create_native_app(
    *,
    session_factory: SessionFactory,
    native_identity_authority_id: UUID,
    slot_offer_ports: QueueSlotOfferHttpPorts | None = None,
    appointment_option_signing_key: bytes | None = None,
    identity_exchange_fingerprint_key: bytes | None = None,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
    operator_actor_resolver: OperatorActorResolver | None = None,
    operator_capability_source: OperatorCapabilitySource | None = None,
    oidc_subject_resolver: OidcHttpSubjectResolver | None = None,
) -> FastAPI:
    """Compose a providerless deployment whose protected routes trust Native evidence.

    This is the zero-external-IdP composition root. Native human sessions and
    first-party workload credentials prove credential possession only; the
    resulting HTTP actor resolver still performs a fresh IdentityBinding and
    Principal-authority lookup on every protected request.

    When ``oidc_subject_resolver`` is provided, JWT-shaped bearers are
    additionally dispatched to the optional federated OIDC arm. Without it the
    deployment behaves exactly as before: a JWT-shaped bearer fails closed as
    unauthenticated and no OIDC configuration is required.
    """

    runtime = build_native_auth_runtime(
        session_factory,
        oidc_runtime=(
            None
            if oidc_subject_resolver is None
            else OidcAuthRuntime(subject_resolver=oidc_subject_resolver)
        ),
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=AgentPolicyActorResolver(
            DelegatedAgentActorResolver(
                runtime.actor_resolver,
                PostgresDelegationReader(session_factory),
            ),
            PostgresAgentPolicyReader(session_factory),
            PostgresAgentBudgetEnforcer(session_factory),
        ),
        slot_offer_ports=slot_offer_ports,
        appointment_option_signing_key=appointment_option_signing_key,
        identity_exchange_fingerprint_key=identity_exchange_fingerprint_key,
        tenant_capability_policy=tenant_capability_policy,
        operator_actor_resolver=operator_actor_resolver,
        operator_capability_source=operator_capability_source,
        native_auth_service=runtime.service,
        native_session_authenticator=runtime.authenticator,
        native_identity_authority_id=native_identity_authority_id,
    )
