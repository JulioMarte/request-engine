import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.identity_link import (
    IDENTITY_LINK_CAPABILITY,
    ConfirmIdentityLinkIntentCommand,
    CreateIdentityLinkIntentCommand,
    IdentityLinkCommands,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityLinkConflict,
    IdentityLinkError,
    IdentityLinkForbidden,
    IdentityLinkInputInvalid,
    IdentityLinkNotConfigured,
    IdentityLinkNotFound,
    IdentityLinkRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.identity_link import (
    IdentityLinkIntentReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.freshness import enforce_step_up
from request_engine.platform.security.http import require_capability
from request_engine.platform.security.native_auth import CredentialInvalid, verify_password
from request_engine.platform.security.native_human_auth import NativeHumanAuthStore
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
)
from request_engine.platform.security.oidc_link import OidcLinkVerifier

_IDENTITY_LINK_TTL_SECONDS = 300


class IdentityLinkIntentCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_authority_id: UUID
    provenance_reference: str = Field(min_length=1, max_length=400)


class IdentityLinkIntentView(BaseModel):
    intent_id: UUID
    expires_at: datetime
    target_authority_id: UUID


class NativeIdentityLinkProofBody(BaseModel):
    """Closed, bounded secret proof DTO for a second native identity.

    The target authority is never supplied by the caller: it is derived from the
    persisted intent inside the authoritative transaction.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["native"] = "native"
    native_identity_id: UUID
    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class OidcIdentityLinkProofBody(BaseModel):
    """Closed, bounded second-proof DTO for a federated OIDC identity.

    The access token is verified against the authority persisted on the intent;
    it is never logged or echoed. The target authority is not caller-supplied.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["oidc"] = "oidc"
    access_token: str = Field(min_length=1, max_length=16384, repr=False)


class IdentityLinkIntentConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof: Annotated[
        NativeIdentityLinkProofBody | OidcIdentityLinkProofBody,
        Field(discriminator="kind"),
    ]
    expected_actor_binding_revision: int = Field(ge=1)
    provenance_reference: str = Field(min_length=1, max_length=400)

    @model_validator(mode="before")
    @classmethod
    def _default_native_proof_kind(cls, data: object) -> object:
        """Keep the pre-existing native proof body (without ``kind``) valid."""

        if not isinstance(data, dict):
            return data
        values = cast(Mapping[str, object], data)
        proof = values.get("proof")
        if isinstance(proof, dict) and "kind" not in proof:
            proof_values = cast(Mapping[str, object], proof)
            return {**values, "proof": {**proof_values, "kind": "native"}}
        return values


class IdentityLinkBindingView(BaseModel):
    binding_id: UUID
    principal_id: UUID
    binding_revision: int


def _require_self_service_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise IdentityLinkForbidden("self-service identity linking requires a HUMAN actor")
    if actor.delegation_id is not None:
        raise IdentityLinkForbidden("delegated actors cannot self-link identities")


async def _verify_native_proof(
    proof_reader: NativeHumanAuthStore,
    proof: NativeIdentityLinkProofBody,
    *,
    target_authority_id: UUID,
) -> None:
    """Verify the second identity's password outside any authoritative lock."""

    snapshot = await proof_reader.read_password_credential(
        identity_authority_id=target_authority_id,
        login_handle=proof.login_handle,
    )
    if (
        snapshot is None
        or snapshot.identity_status is not NativeIdentityStatus.ACTIVE
        or snapshot.credential_status is not NativeCredentialStatus.ACTIVE
        or snapshot.native_identity_id != proof.native_identity_id
    ):
        raise CredentialInvalid("native identity link proof is invalid")
    if not await asyncio.to_thread(verify_password, proof.password, snapshot.verifier):
        raise CredentialInvalid("native identity link proof is invalid")


def add_identity_link_routes(
    router: APIRouter,
    *,
    commands: IdentityLinkCommands,
    proof_reader: NativeHumanAuthStore,
    intent_reader: IdentityLinkIntentReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
    oidc_verifier: OidcLinkVerifier | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    async def create_intent(
        body: IdentityLinkIntentCreateBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> IdentityLinkIntentView:
        require_capability(actor, IDENTITY_LINK_CAPABILITY)
        _require_self_service_actor(actor)
        enforce_step_up(actor, IDENTITY_LINK_CAPABILITY, now=clock())
        actor_binding_id = actor.identity_binding_id
        if actor_binding_id is None:
            raise IdentityLinkForbidden("the current actor has no active tenant identity binding")
        nonce = secrets.token_bytes(32)
        try:
            receipt = await commands.create_identity_link_intent(
                actor,
                CreateIdentityLinkIntentCommand(
                    intent_id=uuid4(),
                    actor_binding_id=actor_binding_id,
                    target_authority_id=body.target_authority_id,
                    nonce_digest=hashlib.sha256(nonce).hexdigest(),
                    ttl_seconds=_IDENTITY_LINK_TTL_SECONDS,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise IdentityLinkInputInvalid(str(exc)) from None
        response.headers["Cache-Control"] = "no-store"
        return IdentityLinkIntentView(
            intent_id=receipt.intent_id,
            expires_at=receipt.expires_at,
            target_authority_id=receipt.target_authority_id,
        )

    async def confirm_intent(
        intent_id: UUID,
        body: IdentityLinkIntentConfirmBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
        response: Response,
    ) -> IdentityLinkBindingView:
        require_capability(actor, IDENTITY_LINK_CAPABILITY)
        _require_self_service_actor(actor)
        enforce_step_up(actor, IDENTITY_LINK_CAPABILITY, now=clock())
        intent = await intent_reader.read_intent(actor, intent_id=intent_id)
        if intent is None or intent.actor_principal_id != actor.principal_id:
            raise IdentityLinkNotFound("identity link intent is not visible in this tenant")
        if intent.status not in {"pending", "consumed"}:
            raise IdentityLinkConflict("identity link intent is no longer pending")
        if intent.status == "pending" and intent.expires_at <= clock():
            raise IdentityLinkConflict("identity link intent has expired")
        native_identity_id: UUID | None = None
        subject_id: str | None = None
        if intent.target_authority_kind == "native":
            if not isinstance(body.proof, NativeIdentityLinkProofBody):
                raise IdentityLinkInputInvalid("the intent requires a native identity proof")
            await _verify_native_proof(
                proof_reader,
                body.proof,
                target_authority_id=intent.target_authority_id,
            )
            native_identity_id = body.proof.native_identity_id
        elif intent.target_authority_kind == "oidc":
            if not isinstance(body.proof, OidcIdentityLinkProofBody):
                raise IdentityLinkInputInvalid("the intent requires an OIDC access token")
            if oidc_verifier is None:
                raise IdentityLinkNotConfigured(
                    "OIDC identity linking is not configured in this deployment"
                )
            subject_id = await oidc_verifier.verify(
                intent.target_authority_id, body.proof.access_token
            )
        else:
            raise IdentityLinkInputInvalid("the intent targets an unsupported authority kind")
        try:
            receipt = await commands.confirm_identity_link_intent(
                actor,
                ConfirmIdentityLinkIntentCommand(
                    intent_id=intent_id,
                    expected_actor_binding_revision=body.expected_actor_binding_revision,
                    binding_id=uuid4(),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                    native_identity_id=native_identity_id,
                    subject_id=subject_id,
                ),
            )
        except ValueError as exc:
            raise IdentityLinkInputInvalid(str(exc)) from None
        response.headers["Cache-Control"] = "no-store"
        return IdentityLinkBindingView(
            binding_id=receipt.binding_id,
            principal_id=receipt.principal_id,
            binding_revision=receipt.binding_revision,
        )

    add_capability_route(
        router,
        "/v1/me/identity-link-intents",
        create_intent,
        methods=["POST"],
        capability=IDENTITY_LINK_CAPABILITY,
        operation_id="identity_link_intent_create",
        owner="tenancy",
        response_model=IdentityLinkIntentView,
        status_code=http_status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/v1/me/identity-link-intents/{intent_id}:confirm",
        confirm_intent,
        methods=["POST"],
        capability=IDENTITY_LINK_CAPABILITY,
        operation_id="identity_link_intent_confirm",
        owner="tenancy",
        response_model=IdentityLinkBindingView,
    )


def add_identity_link_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IdentityLinkError, identity_link_error_handler)


async def identity_link_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, IdentityLinkError):
        raise exc
    status_code, body = _identity_link_error(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=body).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _identity_link_error(exc: IdentityLinkError) -> tuple[int, ErrorBody]:
    if isinstance(exc, IdentityLinkForbidden):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="identity_link_forbidden",
            message="the current actor may not self-link an identity",
            resolution=ErrorResolution.REQUEST_AUTHORITY,
        )
    if isinstance(exc, IdentityLinkNotFound):
        return http_status.HTTP_404_NOT_FOUND, ErrorBody(
            code="identity_link_not_found",
            message="identity link intent was not found in the current tenant",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityLinkRevisionConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="identity_link_revision_conflict",
            message="identity link state changed since the supplied revision",
            retryable=True,
            resolution=ErrorResolution.REFRESH_AND_RETRY,
        )
    if isinstance(exc, IdentityLinkConflict):
        return http_status.HTTP_409_CONFLICT, ErrorBody(
            code="identity_link_conflict",
            message="identity link state conflicts with this request",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityLinkInputInvalid):
        return http_status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorBody(
            code="identity_link_invalid",
            message="the identity link request is invalid",
            resolution=ErrorResolution.FIX_REQUEST,
        )
    if isinstance(exc, IdentityLinkNotConfigured):
        return http_status.HTTP_403_FORBIDDEN, ErrorBody(
            code="identity_link_not_configured",
            message="OIDC identity linking is not configured in this deployment",
            resolution=ErrorResolution.OPERATOR_INTERVENTION,
        )
    return http_status.HTTP_500_INTERNAL_SERVER_ERROR, ErrorBody(
        code="identity_link_error",
        message="the identity link request failed",
        resolution=ErrorResolution.OPERATOR_INTERVENTION,
    )
