from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.adapters.db.native_platform_provisioning_commands import (
    PostgresNativePlatformProvisioningCommands,
)
from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NativePlatformProvisioningConflict,
    NativePlatformProvisioningError,
    NativePlatformProvisioningForbidden,
    NativePlatformProvisioningInvalid,
    NativePlatformProvisioningRevisionConflict,
    ProvisionNativeOrganizationCommand,
    ProvisionNativePlatformProvisionerCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver


class NativePlatformProvisionerBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    native_identity_id: UUID
    provenance_reference: str = Field(min_length=1, max_length=500)


class NativePlatformProvisionerView(BaseModel):
    principal_id: UUID
    binding_id: UUID


class NativeOrganizationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    organization_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    controller_native_identity_id: UUID
    provenance_reference: str = Field(min_length=1, max_length=400)


class NativeOrganizationView(BaseModel):
    organization_id: UUID
    organization_party_id: UUID
    controller_principal_id: UUID
    controller_binding_id: UUID


async def provisioning_error_handler(_: Request, exc: Exception) -> JSONResponse:
    errors: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
        NativePlatformProvisioningForbidden: (
            403,
            "platform_provisioning_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        NativePlatformProvisioningConflict: (
            409,
            "platform_provisioning_conflict",
            ErrorResolution.FIX_REQUEST,
        ),
        NativePlatformProvisioningInvalid: (
            422,
            "platform_provisioning_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        NativePlatformProvisioningRevisionConflict: (
            409,
            "platform_authority_changed",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
    }
    status_code, code, resolution = errors.get(
        type(exc), (500, "platform_provisioning_failed", ErrorResolution.OPERATOR_INTERVENTION)
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The platform provisioning command could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_native_platform_provisioning_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    native_authority_id: UUID,
) -> None:
    commands = PostgresNativePlatformProvisioningCommands(session_factory)
    router = APIRouter(tags=["Platform provisioning"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def create_provisioner(
        body: NativePlatformProvisionerBody,
        response: Response,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
        ],
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
        ],
    ) -> NativePlatformProvisionerView:
        result = await commands.provision_native_platform_provisioner(
            actor,
            ProvisionNativePlatformProvisionerCommand(
                identity_authority_id=native_authority_id,
                native_identity_id=body.native_identity_id,
                provenance_reference=body.provenance_reference,
                idempotency_key=idempotency_key,
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        return NativePlatformProvisionerView(
            principal_id=result.principal_id, binding_id=result.binding_id
        )

    async def create_organization(
        body: NativeOrganizationBody,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
        _bearer: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
        ],
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
        ],
    ) -> NativeOrganizationView:
        result = await commands.provision_native_organization(
            actor,
            ProvisionNativeOrganizationCommand(
                organization_key=body.organization_key,
                display_name=body.display_name,
                identity_authority_id=native_authority_id,
                native_identity_id=body.controller_native_identity_id,
                provenance_reference=body.provenance_reference,
                idempotency_key=idempotency_key,
            ),
        )
        return NativeOrganizationView(
            organization_id=result.organization_id,
            organization_party_id=result.organization_party_id,
            controller_principal_id=result.controller_principal_id,
            controller_binding_id=result.controller_binding_id,
        )

    add_capability_route(
        router,
        "/v1/platform/organizations",
        create_organization,
        capability="organization.provision",
        methods=["POST"],
        operation_id="platform_native_organization_create",
        owner="tenancy",
        status_code=201,
        response_model=NativeOrganizationView,
        responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422)},
    )
    add_capability_route(
        router,
        "/v1/platform/provisioners",
        create_provisioner,
        capability="platform.tenant_provisioner.provision",
        methods=["POST"],
        operation_id="platform_native_provisioner_create",
        owner="tenancy",
        status_code=201,
        response_model=NativePlatformProvisionerView,
        responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 409, 422)},
    )
    app.add_exception_handler(NativePlatformProvisioningError, provisioning_error_handler)
    app.include_router(router)
