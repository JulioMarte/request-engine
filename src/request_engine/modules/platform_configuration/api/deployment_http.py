from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.platform_configuration.adapters.coolify_recovery import (
    CoolifyRecoveryAdapter,
)
from request_engine.modules.platform_configuration.adapters.db.configuration import (
    PostgresPlatformConfigurationCommands,
    PostgresPlatformConfigurationReader,
)
from request_engine.modules.platform_configuration.adapters.db.provider_secrets import (
    PostgresProviderSecretResolver,
)
from request_engine.modules.platform_configuration.api.http import (
    require_platform_configuration_step_up,
)
from request_engine.modules.platform_configuration.application.configuration import (
    ActivateConfiguration,
    StageConfiguration,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.deployment_binding import (
    DEPLOYMENT_BINDING_KIND,
    DEPLOYMENT_BINDING_PROVIDER,
    DeploymentBinding,
    DeploymentRecoveryService,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.secrets.platform_store import PlatformSecretStore
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=160,
        pattern=r"\S",
    ),
]


class DeploymentBindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_url: str = Field(pattern=r"^https://")
    database_uuid: str = Field(min_length=1, max_length=200)
    scheduled_backup_uuid: str | None = Field(default=None, max_length=200)
    s3_storage_uuid: str | None = Field(default=None, max_length=200)
    secret_binding_id: UUID
    expected_active_revision: int | None = Field(default=None, ge=1)


class DeploymentBindingView(BaseModel):
    provider_kind: str
    revision: int
    base_url: str
    database_uuid: str
    scheduled_backup_uuid: str | None
    s3_storage_uuid: str | None
    secret_binding_id: UUID


class DeploymentChangeView(BaseModel):
    field: str
    actual: object | None
    desired: object | None


class DeploymentPlanView(BaseModel):
    binding: DeploymentBindingView
    status: str
    changes: list[DeploymentChangeView]


class DeploymentReconcileView(BaseModel):
    binding: DeploymentBindingView
    action: str
    before_status: str
    after_status: str
    changes: list[DeploymentChangeView]


def install_deployment_recovery_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    secret_store: PlatformSecretStore | None,
) -> None:
    reader = PostgresPlatformConfigurationReader(read_session_factory)
    commands = PostgresPlatformConfigurationCommands(write_session_factory)
    secret_resolver = PostgresProviderSecretResolver(write_session_factory)
    service = DeploymentRecoveryService(
        reader=reader,
        secret_resolver=secret_resolver,
        secret_store=secret_store,
        adapter_factory=lambda binding, token: CoolifyRecoveryAdapter(
            base_url=binding.base_url,
            api_token=token,
        ),
    )
    router = APIRouter(tags=["Platform deployment recovery"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def configure(
        body: DeploymentBindingBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> DeploymentBindingView:
        require_platform_configuration_step_up(actor)
        metadata = await reader.get_secret_binding(actor, body.secret_binding_id)
        staged = await commands.stage(
            actor,
            StageConfiguration(
                configuration_kind=DEPLOYMENT_BINDING_KIND,
                provider_kind=DEPLOYMENT_BINDING_PROVIDER,
                configuration={
                    "base_url": body.base_url.rstrip("/"),
                    "database_uuid": body.database_uuid,
                    "scheduled_backup_uuid": body.scheduled_backup_uuid,
                    "s3_storage_uuid": body.s3_storage_uuid,
                },
                secret_binding_id=body.secret_binding_id,
                idempotency_key=f"{idempotency_key}:stage",
            ),
        )
        await commands.validate(
            actor,
            ValidateConfiguration(
                configuration_kind=DEPLOYMENT_BINDING_KIND,
                revision=staged.revision,
                expected_binding_revision=metadata.revision,
                expected_backend_version=metadata.backend_version,
                idempotency_key=f"{idempotency_key}:validate",
            ),
        )
        await commands.activate(
            actor,
            ActivateConfiguration(
                configuration_kind=DEPLOYMENT_BINDING_KIND,
                revision=staged.revision,
                expected_active_revision=body.expected_active_revision,
                idempotency_key=f"{idempotency_key}:activate",
            ),
        )
        rows = await reader.list_revisions(actor, DEPLOYMENT_BINDING_KIND)
        active = next(row for row in rows if row.revision == staged.revision)
        binding = DeploymentBinding(
            provider_kind=active.provider_kind,
            base_url=str(active.configuration["base_url"]),
            database_uuid=str(active.configuration["database_uuid"]),
            scheduled_backup_uuid=_optional(active.configuration["scheduled_backup_uuid"]),
            s3_storage_uuid=_optional(active.configuration["s3_storage_uuid"]),
            secret_binding_id=body.secret_binding_id,
            revision=active.revision,
        )
        return _binding_view(binding)

    async def plan(
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> DeploymentPlanView:
        binding, result = await service.plan(actor)
        return DeploymentPlanView(
            binding=_binding_view(binding),
            status=result.status,
            changes=[
                DeploymentChangeView(
                    field=change.field,
                    actual=change.actual,
                    desired=change.desired,
                )
                for change in result.changes
            ],
        )

    async def reconcile(
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> DeploymentReconcileView:
        require_platform_configuration_step_up(actor)
        binding, result = await service.reconcile(actor)
        return DeploymentReconcileView(
            binding=_binding_view(binding),
            action=result.action,
            before_status=result.before.status,
            after_status=result.after.status,
            changes=[
                DeploymentChangeView(
                    field=change.field,
                    actual=change.actual,
                    desired=change.desired,
                )
                for change in result.before.changes
            ],
        )

    add_capability_route(
        router,
        "/v1/platform/deployment-recovery",
        configure,
        capability="platform.configuration.activate",
        methods=["PUT"],
        operation_id="platform_deployment_recovery_configure",
        owner="platform_configuration",
        response_model=DeploymentBindingView,
    )
    add_capability_route(
        router,
        "/v1/platform/deployment-recovery:plan",
        plan,
        capability="platform.configuration.read",
        methods=["GET"],
        operation_id="platform_deployment_recovery_plan",
        owner="platform_configuration",
        response_model=DeploymentPlanView,
    )
    add_capability_route(
        router,
        "/v1/platform/deployment-recovery:reconcile",
        reconcile,
        capability="platform.configuration.activate",
        methods=["POST"],
        operation_id="platform_deployment_recovery_reconcile",
        owner="platform_configuration",
        response_model=DeploymentReconcileView,
    )
    app.include_router(router)


def _binding_view(binding: DeploymentBinding) -> DeploymentBindingView:
    return DeploymentBindingView(
        provider_kind=binding.provider_kind,
        revision=binding.revision,
        base_url=binding.base_url,
        database_uuid=binding.database_uuid,
        scheduled_backup_uuid=binding.scheduled_backup_uuid,
        s3_storage_uuid=binding.s3_storage_uuid,
        secret_binding_id=binding.secret_binding_id,
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)
