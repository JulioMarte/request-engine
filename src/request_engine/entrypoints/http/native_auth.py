from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from request_engine.platform.security.native_auth import parse_opaque_token
from request_engine.platform.security.native_http import bearer_token
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)


class NativeLoginRequest(BaseModel):
    login_handle: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class NativePasswordRotationRequest(BaseModel):
    login_handle: str = Field(min_length=1, max_length=320)
    current_password: str = Field(min_length=1, max_length=1024, repr=False)
    new_password: str = Field(min_length=1, max_length=1024, repr=False)


class NativeSessionResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: str = "Bearer"
    expires_at: datetime


class NativeCredentialRotationResponse(BaseModel):
    credential_id: UUID


def create_native_auth_router(
    *,
    service: NativeHumanAuthService,
    authenticator: NativeSessionAuthenticator,
    identity_authority_id: UUID,
) -> APIRouter:
    router = APIRouter(prefix="/auth/native", tags=["Native authentication"])

    async def create_session(
        payload: NativeLoginRequest,
        response: Response,
    ) -> NativeSessionResponse:
        issued = await service.authenticate_password(
            identity_authority_id=identity_authority_id,
            login_handle=payload.login_handle,
            password=payload.password,
        )
        _prevent_secret_caching(response)
        return NativeSessionResponse(
            access_token=issued.raw_token,
            expires_at=issued.expires_at,
        )

    async def revoke_current_session(request: Request, response: Response) -> None:
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        await service.revoke_session(
            native_identity_id=UUID(subject.subject_id),
            session_id=parsed.token_id,
        )
        _prevent_secret_caching(response)

    async def revoke_all_sessions(request: Request, response: Response) -> None:
        raw_token = bearer_token(request)
        subject = await authenticator.authenticate(NativeSessionEvidence(raw_token))
        await service.revoke_all_sessions(native_identity_id=UUID(subject.subject_id))
        _prevent_secret_caching(response)

    async def rotate_password(
        payload: NativePasswordRotationRequest,
        response: Response,
    ) -> NativeCredentialRotationResponse:
        credential_id = await service.rotate_password(
            identity_authority_id=identity_authority_id,
            login_handle=payload.login_handle,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
        _prevent_secret_caching(response)
        return NativeCredentialRotationResponse(credential_id=credential_id)

    router.add_api_route(
        "/sessions",
        create_session,
        methods=["POST"],
        operation_id="nativeSessionCreate",
        response_model=NativeSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/sessions/current",
        revoke_current_session,
        methods=["DELETE"],
        operation_id="nativeSessionRevokeCurrent",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    router.add_api_route(
        "/sessions",
        revoke_all_sessions,
        methods=["DELETE"],
        operation_id="nativeSessionRevokeAll",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    router.add_api_route(
        "/password",
        rotate_password,
        methods=["PUT"],
        operation_id="nativePasswordRotate",
        response_model=NativeCredentialRotationResponse,
    )
    return router


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
