from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    http_exception_handler,
    idempotency_conflict_handler,
    integrity_error_handler,
    request_validation_error_handler,
)
from request_engine.entrypoints.http.operational_composition import install_operational_modules
from request_engine.entrypoints.http.operational_errors import (
    operational_authority_required_handler,
    public_contact_validation_error_handler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.public_contacts import PublicContactValidationError
from request_engine.platform.security.execution_context import clear_actor_context
from request_engine.platform.security.http import (
    ActorResolver,
    AuthenticationRequired,
    RequestExecutionActorResolver,
    request_correlation_id,
)
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired

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


def create_operational_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> FastAPI:
    """Compose the authenticated operator/control-plane HTTP process."""

    request_actor_resolver = RequestExecutionActorResolver(actor_resolver)
    app = FastAPI(
        title="Request Engine Operations",
        version="0.1.0",
        description=(
            "Operator-only configuration API. Tenant and principal identity come from the "
            "deployment ActorResolver; commands additionally require exact Representation scopes."
        ),
    )
    app.middleware("http")(_request_execution_context)
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(
        OperationalAuthorityRequired,
        operational_authority_required_handler,
    )
    app.add_exception_handler(
        PublicContactValidationError,
        public_contact_validation_error_handler,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    install_operational_modules(
        app,
        session_factory=session_factory,
        actor_resolver=request_actor_resolver,
    )
    return app
