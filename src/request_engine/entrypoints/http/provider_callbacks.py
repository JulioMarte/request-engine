"""Provider-event callback trust boundary (inbound transport outcome reports).

This is not a capability operation: no Principal/ActorContext exists. The
deployment-configured ProviderCallbackAuthenticator derives organization,
provider and connection from verified credentials before the body is parsed;
the body contributes only the provider's event identity and the opaque payload.
The event is persisted before interpretation (``platform.events.callbacks``);
semantic interpretation happens later in the fenced ProviderEvent worker.
"""

import json
from typing import cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import render_error_response
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.callbacks import (
    ProviderCallbackAuthenticationFailed,
    ProviderCallbackAuthenticator,
    record_authenticated_provider_callback,
)
from request_engine.platform.events.errors import ProviderEventDedupeConflict
from request_engine.platform.http.errors import ErrorBody, ErrorResolution

PROVIDER_EVENT_PATH = "/v1/provider-events/{provider_key}/{connection_key}"
PROVIDER_EVENT_OPERATION_ID = "recordProviderEvent"
MAX_PROVIDER_EVENT_BODY_BYTES = 65_536
_MAX_PROVIDER_EVENT_ID_LENGTH = 200
_FOREIGN_KEY_VIOLATION = "23503"
_NO_STORE = {"Cache-Control": "no-store"}


class _InvalidProviderEvent(ValueError):
    pass


def create_provider_callback_router(
    *,
    session_factory: SessionFactory,
    authenticator: ProviderCallbackAuthenticator,
) -> APIRouter:
    router = APIRouter()

    async def record_provider_event(
        request: Request, provider_key: str, connection_key: str
    ) -> JSONResponse:
        del provider_key, connection_key  # authority comes from the authenticator
        if _declared_length(request) > MAX_PROVIDER_EVENT_BODY_BYTES:
            return _too_large()
        try:
            trusted = await authenticator.authenticate_callback(request)
        except ProviderCallbackAuthenticationFailed:
            return _unauthenticated()
        body = await request.body()
        if len(body) > MAX_PROVIDER_EVENT_BODY_BYTES:
            return _too_large()
        try:
            provider_event_id, payload = _parse(body)
        except _InvalidProviderEvent as exc:
            return _error(
                422,
                "invalid_provider_event",
                str(exc),
                ErrorResolution.FIX_REQUEST,
            )
        try:
            receipt = await record_authenticated_provider_callback(
                session_factory,
                trusted,
                provider_event_id=provider_event_id,
                payload=payload,
            )
        except ProviderEventDedupeConflict:
            return _error(
                status.HTTP_409_CONFLICT,
                "provider_event_conflict",
                "this provider event id was already recorded with a different payload",
                ErrorResolution.OPERATOR_INTERVENTION,
            )
        except IntegrityError as exc:
            # A verified signature for an organization that does not exist is
            # indistinguishable from any other authentication failure.
            if getattr(exc.orig, "sqlstate", None) == _FOREIGN_KEY_VIOLATION:
                return _unauthenticated()
            raise
        return JSONResponse(
            {"provider_event_id": provider_event_id, "replay": receipt.replay},
            status_code=status.HTTP_200_OK if receipt.replay else status.HTTP_202_ACCEPTED,
            headers=_NO_STORE,
        )

    router.add_api_route(
        PROVIDER_EVENT_PATH,
        record_provider_event,
        methods=["POST"],
        operation_id=PROVIDER_EVENT_OPERATION_ID,
        include_in_schema=False,
    )
    return router


def _declared_length(request: Request) -> int:
    raw = request.headers.get("content-length", "0")
    return int(raw) if raw.isdigit() else 0


def _parse(body: bytes) -> tuple[str, dict[str, object]]:
    try:
        parsed: object = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise _InvalidProviderEvent("the body must be a JSON object") from None
    if not isinstance(parsed, dict):
        raise _InvalidProviderEvent("the body must be a JSON object")
    document = cast(dict[str, object], parsed)
    if set(document) != {"provider_event_id", "payload"}:
        raise _InvalidProviderEvent("the body must contain exactly provider_event_id and payload")
    provider_event_id = document["provider_event_id"]
    payload = document["payload"]
    if (
        not isinstance(provider_event_id, str)
        or not provider_event_id.strip()
        or len(provider_event_id) > _MAX_PROVIDER_EVENT_ID_LENGTH
    ):
        raise _InvalidProviderEvent("provider_event_id must be a non-empty string")
    if not isinstance(payload, dict):
        raise _InvalidProviderEvent("payload must be a JSON object")
    return provider_event_id, cast(dict[str, object], payload)


def _unauthenticated() -> JSONResponse:
    return _error(
        status.HTTP_401_UNAUTHORIZED,
        "provider_callback_authentication_failed",
        "the provider callback could not be authenticated",
        ErrorResolution.REAUTHENTICATE,
    )


def _too_large() -> JSONResponse:
    return _error(
        413,
        "request_body_too_large",
        "the provider event body exceeds the callback limit",
        ErrorResolution.FIX_REQUEST,
    )


def _error(status_code: int, code: str, message: str, resolution: ErrorResolution) -> JSONResponse:
    return render_error_response(
        status_code,
        ErrorBody(code=code, message=message, retryable=False, resolution=resolution),
        headers=_NO_STORE,
    )
