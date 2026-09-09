from fastapi import APIRouter, FastAPI, Request

from request_engine.modules.tenancy.adapters.db.agent_governance_commands import (
    PostgresAgentGovernanceCommands,
)
from request_engine.modules.tenancy.adapters.db.agent_policy_commands import (
    PostgresAgentPolicyCommands,
)
from request_engine.modules.tenancy.adapters.db.bootstrap_operational_authority_commands import (
    PostgresBootstrapOperationalAuthorityCommands,
)
from request_engine.modules.tenancy.adapters.db.delegation_commands import (
    PostgresDelegationCommands,
)
from request_engine.modules.tenancy.adapters.db.onboarding_party_reader import (
    PostgresBusinessPartyReader,
)
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.adapters.db.party_authority_operational_reader import (
    PostgresOperationalAuthorityPartyReader,
)
from request_engine.modules.tenancy.adapters.db.party_authority_reader import (
    PostgresPartyAuthorityReader,
)
from request_engine.modules.tenancy.adapters.db.principal_authority_reader import (
    PostgresPrincipalAuthorityReader,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_commands import (
    PostgresPrincipalContactCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.api.agent_governance_errors import (
    add_agent_governance_error_handlers,
)
from request_engine.modules.tenancy.api.agent_governance_routes import (
    add_agent_governance_routes,
)
from request_engine.modules.tenancy.api.agent_policy_errors import (
    add_agent_policy_error_handlers,
)
from request_engine.modules.tenancy.api.agent_policy_routes import add_agent_policy_routes
from request_engine.modules.tenancy.api.bootstrap_authority_routes import (
    bootstrap_authority_error_handler,
    create_bootstrap_authority_router,
)
from request_engine.modules.tenancy.api.delegation_errors import add_delegation_error_handlers
from request_engine.modules.tenancy.api.delegation_routes import add_delegation_routes
from request_engine.modules.tenancy.api.identity_exchange_http import install_identity_exchange_http
from request_engine.modules.tenancy.api.operational_router import create_operational_router
from request_engine.modules.tenancy.api.party_registry_http import install_party_registry_http
from request_engine.modules.tenancy.api.staff_contact_errors import add_staff_contact_error_handlers
from request_engine.modules.tenancy.api.staff_contact_routes import add_staff_contact_routes
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.modules.tenancy.api.staff_membership_routes import add_staff_membership_routes
from request_engine.modules.tenancy.application.commands.staff_membership import (
    StaffMembershipCommands,
)
from request_engine.modules.tenancy.application.errors import BootstrapAuthorityPartyInvalid
from request_engine.modules.tenancy.contracts.authority import (
    OperationalAuthorityPartyReader,
    PartyAuthorityReader,
)
from request_engine.modules.tenancy.contracts.onboarding_readiness import BusinessPartyReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver
from request_engine.platform.security.principal_authority import PrincipalAuthorityReader


def build_party_authority_reader(session_factory: SessionFactory) -> PartyAuthorityReader:
    """Compose the tenant-owned Party authority reader behind the module API surface."""

    return PostgresPartyAuthorityReader(session_factory)


def build_operational_authority_party_reader(
    session_factory: SessionFactory,
) -> OperationalAuthorityPartyReader:
    """Compose the fail-closed operational Party authority reader for composition roots."""

    return PostgresOperationalAuthorityPartyReader(session_factory)


def build_onboarding_business_party_reader(session_factory: SessionFactory) -> BusinessPartyReader:
    """Compose the tenancy-owned business-Party readiness reader for composition roots."""

    return PostgresBusinessPartyReader(session_factory)


def build_principal_authority_reader(session_factory: SessionFactory) -> PrincipalAuthorityReader:
    """Compose the RE-owned Principal authority reader behind the tenancy API surface."""

    return PostgresPrincipalAuthorityReader(session_factory)


def build_staff_membership_commands(session_factory: SessionFactory) -> StaffMembershipCommands:
    """Compose the tenant-owned Staff lifecycle writer behind the module API surface."""

    return PostgresStaffMembershipCommands(session_factory)


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    identity_exchange_fingerprint_key: bytes | None = None,
) -> None:
    """Connect tenancy Party, identity-exchange and staff administration HTTP surfaces."""

    app.add_exception_handler(BootstrapAuthorityPartyInvalid, bootstrap_authority_error_handler)
    install_party_registry_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_identity_exchange_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        fingerprint_key=identity_exchange_fingerprint_key,
    )
    app.include_router(
        create_bootstrap_authority_router(
            handler=PostgresBootstrapOperationalAuthorityCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    add_staff_contact_error_handlers(app)
    add_staff_membership_error_handlers(app)

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    contact_commands = PostgresPrincipalContactCommands(session_factory)
    staff_router = APIRouter(prefix="/v1/staff", tags=["staff"])
    add_staff_contact_routes(
        staff_router,
        register_handler=contact_commands,
        verification_handler=contact_commands,
        confirm_handler=contact_commands,
        authenticated_actor=authenticated_actor,
    )
    add_staff_membership_routes(
        staff_router,
        commands=PostgresStaffMembershipCommands(session_factory),
        authenticated_actor=authenticated_actor,
    )
    app.include_router(staff_router)

    add_agent_governance_error_handlers(app)
    add_agent_policy_error_handlers(app)
    agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])
    add_agent_governance_routes(
        agents_router,
        commands=PostgresAgentGovernanceCommands(session_factory),
        authenticated_actor=authenticated_actor,
    )
    add_agent_policy_routes(
        agents_router,
        commands=PostgresAgentPolicyCommands(session_factory),
        authenticated_actor=authenticated_actor,
    )
    app.include_router(agents_router)

    add_delegation_error_handlers(app)
    delegations_router = APIRouter(prefix="/v1/delegations", tags=["delegations"])
    add_delegation_routes(
        delegations_router,
        commands=PostgresDelegationCommands(session_factory),
        authenticated_actor=authenticated_actor,
    )
    app.include_router(delegations_router)


def install_operational_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    commands = PostgresOperationalProfileCommands(session_factory)
    app.include_router(
        create_operational_router(
            profile_handler=commands,
            contacts_handler=commands,
            actor_resolver=actor_resolver,
        )
    )
