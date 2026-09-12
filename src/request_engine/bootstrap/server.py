"""Deployable native-first ASGI factory: uvicorn ...server:create_app --factory."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from request_engine.bootstrap.settings import HttpSettings
from request_engine.entrypoints.http.app import create_native_app
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.platform.db.oidc_authority_reader import PostgresOidcAuthorityReader
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.oidc_http import OidcHttpSubjectResolver


def create_app() -> FastAPI:
    """Fail on missing configuration; external identity is explicitly opt-in."""
    settings = HttpSettings.model_validate({})
    engine = create_postgres_engine(settings.database_url.get_secret_value())
    sessions = create_session_factory(engine)
    oidc = (
        OidcHttpSubjectResolver(authority_reader=PostgresOidcAuthorityReader(sessions))
        if settings.oidc_enabled
        else None
    )
    app = create_native_app(
        session_factory=sessions,
        native_identity_authority_id=settings.native_identity_authority_id,
        appointment_option_signing_key=settings.appointment_option_signing_key.get_secret_value().encode(),
        identity_exchange_fingerprint_key=settings.identity_exchange_fingerprint_key.get_secret_value().encode(),
        oidc_subject_resolver=oidc,
        slot_offer_ports=QueueSlotOfferHttpPorts(
            capacity=CapacitySafeSlotOfferCapacity(),
            notification=PostgresSlotOfferNotificationIntent(),
        ),
    )
    existing_lifespan = app.router.lifespan_context

    async def native_authority_ready() -> bool:
        async with asyncio.timeout(settings.database_probe_timeout_seconds):
            async with engine.connect() as connection:
                return (
                    await connection.scalar(
                        text("SELECT request_auth.is_native_authority_ready(:authority_id)"),
                        {"authority_id": settings.native_identity_authority_id},
                    )
                    is True
                )

    async def verify_runtime_role() -> None:
        async with asyncio.timeout(settings.database_probe_timeout_seconds):
            async with engine.connect() as connection:
                allowed = await connection.scalar(
                    text("""
                    SELECT NOT (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole
                                OR r.rolcreatedb OR r.rolreplication)
                       AND pg_has_role(current_user, 'request_engine_app', 'USAGE')
                       AND NOT EXISTS (
                           SELECT 1 FROM pg_roles forbidden
                           WHERE forbidden.oid <> r.oid
                             AND forbidden.rolname <> 'request_engine_app'
                             AND pg_has_role(r.oid, forbidden.oid, 'MEMBER')
                       )
                    FROM pg_roles r WHERE r.rolname = current_user
                """)
                )
        if allowed is not True:
            raise RuntimeError("HTTP database login violates least-privilege requirements")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        try:
            await verify_runtime_role()
            if not await native_authority_ready():
                raise RuntimeError("Configured native identity authority is unavailable")
            async with existing_lifespan(application):
                yield
        finally:
            try:
                if oidc is not None:
                    await oidc.aclose()
            finally:
                await engine.dispose()

    app.router.lifespan_context = lifespan

    async def live() -> dict[str, str]:
        return {"status": "alive"}

    async def ready() -> JSONResponse:
        try:
            available = await native_authority_ready()
        except (SQLAlchemyError, OSError, TimeoutError):
            available = False
        return JSONResponse(
            {"status": "ready" if available else "unavailable"},
            status_code=200 if available else 503,
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route("/health/live", live, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/ready", ready, methods=["GET"], include_in_schema=False)
    return app
