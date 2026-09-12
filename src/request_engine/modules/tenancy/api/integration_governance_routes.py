from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from request_engine.modules.tenancy.api.integration_governance_models import (
    IntegrationAuthorityReplaceBody,
    IntegrationAuthorityReplaceView,
    IntegrationCredentialRotateBody,
    IntegrationCredentialRotateView,
    IntegrationCredentialView,
    IntegrationLifecycleBody,
    IntegrationListView,
    IntegrationProvisionBody,
    IntegrationProvisionView,
    IntegrationStatusTransitionBody,
    IntegrationStatusTransitionView,
    IntegrationView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.integration_governance import (
    IntegrationGovernanceCommands,
    ProvisionIntegrationCommand,
    ReplaceIntegrationAuthorityCommand,
    RotateIntegrationCredentialCommand,
    TransitionIntegrationStatusCommand,
)
from request_engine.modules.tenancy.application.errors import (
    IntegrationGovernanceForbidden,
    IntegrationGovernanceInputInvalid,
)
from request_engine.modules.tenancy.application.queries.integration_governance import (
    IntegrationGovernanceReader,
    IntegrationSummary,
    ListIntegrationsQuery,
)
from request_engine.modules.tenancy.domain.integration_governance import IntegrationStatus
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


def add_integration_governance_routes(
    router: APIRouter,
    *,
    commands: IntegrationGovernanceCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
    reader: IntegrationGovernanceReader | None = None,
) -> None:
    def authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise IntegrationGovernanceForbidden(
                "integration governance commands require a HUMAN actor"
            )

    async def provision_integration(
        body: IntegrationProvisionBody,
        response: Response,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IntegrationProvisionView:
        authorize(actor, "integration.provision")
        response.headers["Cache-Control"] = "no-store"
        try:
            result = await commands.provision_integration(
                actor,
                ProvisionIntegrationCommand(
                    identity_authority_id=body.identity_authority_id,
                    credential_expires_at=body.credential_expires_at,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IntegrationGovernanceInputInvalid(str(exc)) from None
        return IntegrationProvisionView(
            principal_id=result.principal_id,
            workload_identity_id=result.workload_identity_id,
            credential_id=result.credential_id,
            binding_id=result.binding_id,
            authority_revision=result.authority_revision,
            workload_token=result.workload_token,
        )

    async def replace_authority(
        integration_principal_id: UUID,
        body: IntegrationAuthorityReplaceBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IntegrationAuthorityReplaceView:
        authorize(actor, "integration.manage_authority")
        try:
            revision = await commands.replace_integration_authority(
                actor,
                ReplaceIntegrationAuthorityCommand(
                    integration_principal_id=integration_principal_id,
                    expected_authority_revision=body.expected_authority_revision,
                    desired_capabilities=tuple(body.desired_capabilities),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IntegrationGovernanceInputInvalid(str(exc)) from None
        return IntegrationAuthorityReplaceView(authority_revision=revision)

    async def transition_status(
        integration_principal_id: UUID,
        body: IntegrationStatusTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IntegrationStatusTransitionView:
        authorize(actor, "integration.suspend")
        try:
            revision = await commands.transition_integration_status(
                actor,
                TransitionIntegrationStatusCommand(
                    integration_principal_id=integration_principal_id,
                    expected_revision=body.expected_revision,
                    target_status=IntegrationStatus(body.target_status),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IntegrationGovernanceInputInvalid(str(exc)) from None
        return IntegrationStatusTransitionView(authority_revision=revision)

    async def rotate_credential(
        integration_principal_id: UUID,
        body: IntegrationCredentialRotateBody,
        response: Response,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> IntegrationCredentialRotateView:
        authorize(actor, "integration.provision")
        response.headers["Cache-Control"] = "no-store"
        try:
            result = await commands.rotate_integration_credential(
                actor,
                RotateIntegrationCredentialCommand(
                    integration_principal_id=integration_principal_id,
                    expected_revision=body.expected_revision,
                    credential_expires_at=body.credential_expires_at,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IntegrationGovernanceInputInvalid(str(exc)) from None
        return IntegrationCredentialRotateView(
            credential_id=result.credential_id,
            authority_revision=result.authority_revision,
            workload_token=result.workload_token,
        )

    def lifecycle_endpoint(
        target: IntegrationStatus, capability: str
    ) -> Callable[..., Awaitable[IntegrationStatusTransitionView]]:
        async def transition(
            integration_principal_id: UUID,
            body: IntegrationLifecycleBody,
            actor: Annotated[ActorContext, Depends(authenticated_actor)],
            idempotency_key: IdempotencyKey,
        ) -> IntegrationStatusTransitionView:
            authorize(actor, capability)
            try:
                revision = await commands.transition_integration_status(
                    actor,
                    TransitionIntegrationStatusCommand(
                        integration_principal_id=integration_principal_id,
                        expected_revision=body.expected_revision,
                        target_status=target,
                        provenance_reference=body.provenance_reference,
                        idempotency_key=idempotency_key,
                    ),
                )
            except ValueError as exc:
                raise IntegrationGovernanceInputInvalid(str(exc)) from None
            return IntegrationStatusTransitionView(authority_revision=revision)

        return transition

    add_capability_route(
        router,
        "",
        provision_integration,
        capability="integration.provision",
        methods=["POST"],
        operation_id="integration_provision",
        owner="tenancy",
        response_model=IntegrationProvisionView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{integration_principal_id}/authority",
        replace_authority,
        capability="integration.manage_authority",
        methods=["PUT"],
        operation_id="integration_manage_authority",
        owner="tenancy",
        response_model=IntegrationAuthorityReplaceView,
    )
    add_capability_route(
        router,
        "/{integration_principal_id}/status",
        transition_status,
        capability="integration.suspend",
        methods=["PUT"],
        operation_id="integration_suspend",
        owner="tenancy",
        response_model=IntegrationStatusTransitionView,
        deprecated=True,
    )
    add_capability_route(
        router,
        "/{integration_principal_id}/credentials:rotate",
        rotate_credential,
        capability="integration.provision",
        methods=["POST"],
        operation_id="integration_credential_rotate",
        owner="tenancy",
        response_model=IntegrationCredentialRotateView,
    )
    for action, target, capability in (
        ("activate", IntegrationStatus.ACTIVE, "integration.provision"),
        ("suspend", IntegrationStatus.SUSPENDED, "integration.suspend"),
        ("revoke", IntegrationStatus.REVOKED, "integration.suspend"),
    ):
        add_capability_route(
            router,
            "/{integration_principal_id}:" + action,
            lifecycle_endpoint(target, capability),
            capability=capability,
            methods=["POST"],
            operation_id="integration_" + action + "_command",
            owner="tenancy",
            response_model=IntegrationStatusTransitionView,
        )
    if reader is not None:
        add_integration_governance_read_routes(
            router,
            reader=reader,
            authenticated_actor=authenticated_actor,
        )


def _integration_view(summary: IntegrationSummary) -> IntegrationView:
    return IntegrationView(
        principal_id=summary.principal_id,
        authority_revision=summary.authority_revision,
        status=summary.status.value,
        binding_id=summary.binding_id,
        workload_identity_id=summary.workload_identity_id,
        identity_authority_id=summary.identity_authority_id,
        capabilities=list(summary.capabilities),
        credentials=[
            IntegrationCredentialView(
                credential_id=item.credential_id,
                status=item.status,
                expires_at=item.expires_at,
                created_at=item.created_at,
            )
            for item in summary.credentials
        ],
        provenance_complete=summary.provenance_complete,
    )


def add_integration_governance_read_routes(
    router: APIRouter,
    *,
    reader: IntegrationGovernanceReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    """Composition seam: register integration.read as a tenant-control query first."""

    async def read_integration(
        integration_principal_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> IntegrationView:
        require_capability(actor, "integration.read")
        return _integration_view(await reader.read_integration(actor, integration_principal_id))

    async def list_integrations(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        after: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> IntegrationListView:
        require_capability(actor, "integration.read")
        items = await reader.list_integrations(
            actor, ListIntegrationsQuery(after=after, limit=limit)
        )
        return IntegrationListView(
            items=[_integration_view(item) for item in items],
            next_after=items[-1].principal_id if len(items) == limit else None,
        )

    add_capability_route(
        router,
        "",
        list_integrations,
        capability="integration.read",
        methods=["GET"],
        operation_id="integration_list",
        owner="tenancy",
        response_model=IntegrationListView,
    )
    add_capability_route(
        router,
        "/{integration_principal_id}",
        read_integration,
        capability="integration.read",
        methods=["GET"],
        operation_id="integration_read",
        owner="tenancy",
        response_model=IntegrationView,
    )
