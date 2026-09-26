"""Deployable native-first ASGI factory: uvicorn ...server:create_app --factory."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from request_engine.bootstrap.appointment_signing import (
    AppointmentSigningSecretStoreSettings,
    build_appointment_signing_secret_store,
)
from request_engine.bootstrap.outbound_fence import OutboundSideEffectFence
from request_engine.bootstrap.recovery_delivery import build_native_recovery_messenger
from request_engine.bootstrap.settings import HttpSettings
from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_identity_link_verifier
from request_engine.modules.booking.adapters.appointment_options import (
    ReloadableSignedAppointmentOptionCodec,
)
from request_engine.modules.booking.adapters.appointment_signing_reference import (
    PostgresAppointmentSigningReferenceSource,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.adapters.managed_appointment_signing import (
    AppointmentSigningKeyringUnavailable,
    ManagedAppointmentSigningKeyringResolver,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.platform.db.oidc_authority_reader import PostgresOidcAuthorityReader
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.oidc_http import OidcHttpSubjectResolver
from request_engine.platform.security.webauthn import WebAuthnPolicy


def create_app() -> FastAPI:
    """Fail on missing bootstrap config; managed OIDC is governed by database state."""
    settings = HttpSettings.model_validate({})
    engine = create_postgres_engine(settings.database_url.get_secret_value())
    sessions = create_session_factory(engine)
    # The resolver is always present, but it has no routing authority until an
    # identity.oidc revision is activated.  This removes the second source of
    # truth that REQUEST_ENGINE_OIDC_ENABLED previously created.
    oidc = OidcHttpSubjectResolver(authority_reader=PostgresOidcAuthorityReader(sessions))
    identity_link_verifier = build_identity_link_verifier(sessions)
    outbound_fence = OutboundSideEffectFence.from_environment()
    bootstrap_recovery_messenger = build_native_recovery_messenger()
    native_recovery_messenger = outbound_fence.recovery(bootstrap_recovery_messenger)

    bootstrap_signing_key = (
        None
        if settings.appointment_option_signing_key is None
        else settings.appointment_option_signing_key.get_secret_value().encode()
    )
    signing_store_settings = AppointmentSigningSecretStoreSettings()
    signing_store = build_appointment_signing_secret_store(signing_store_settings)
    if signing_store is None and bootstrap_signing_key is None:
        raise RuntimeError(
            "appointment option signing requires either the legacy signing key "
            "or managed signing OpenBao configuration"
        )
    signing_codec = ReloadableSignedAppointmentOptionCodec(bootstrap_signing_key)
    signing_resolver = (
        None
        if signing_store is None
        else ManagedAppointmentSigningKeyringResolver(
            source=PostgresAppointmentSigningReferenceSource(sessions),
            secret_store=signing_store,
            poll_interval_seconds=signing_store_settings.poll_interval_seconds,
        )
    )

    app = create_native_app(
        session_factory=sessions,
        native_identity_authority_id=settings.native_identity_authority_id,
        appointment_option_codec=signing_codec,
        identity_exchange_fingerprint_key=(
            settings.identity_exchange_fingerprint_key.get_secret_value().encode()
        ),
        oidc_subject_resolver=oidc,
        identity_link_verifier=identity_link_verifier,
        webauthn_policy=WebAuthnPolicy(
            rp_id=settings.webauthn_rp_id,
            rp_name=settings.webauthn_rp_name,
            allowed_origins=frozenset(
                origin.strip()
                for origin in settings.webauthn_allowed_origins.split(",")
                if origin.strip()
            ),
        ),
        webauthn_decoy_key=settings.webauthn_decoy_key.get_secret_value().encode(),
        native_recovery_messenger=native_recovery_messenger,
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

    async def refresh_managed_signing() -> None:
        if signing_resolver is None:
            return
        keyring = await signing_resolver.resolve(force_refresh=True)
        if keyring is None:
            if bootstrap_signing_key is None:
                signing_codec.disable()
            else:
                signing_codec.replace_signing_key(bootstrap_signing_key)
            return
        signing_codec.replace_keyring(keyring)

    async def signing_refresh_loop() -> None:
        assert signing_resolver is not None
        while True:
            await asyncio.sleep(signing_resolver.poll_interval_seconds)
            try:
                await refresh_managed_signing()
            except (AppointmentSigningKeyringUnavailable, SQLAlchemyError, OSError, TimeoutError):
                signing_codec.disable()

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
        signing_task: asyncio.Task[None] | None = None
        try:
            await verify_runtime_role()
            if not await native_authority_ready():
                raise RuntimeError("Configured native identity authority is unavailable")
            if signing_resolver is not None:
                try:
                    await refresh_managed_signing()
                except (
                    AppointmentSigningKeyringUnavailable,
                    SQLAlchemyError,
                    OSError,
                    TimeoutError,
                ) as exc:
                    signing_codec.disable()
                    raise RuntimeError(
                        "managed appointment signing could not be initialized"
                    ) from exc
                signing_task = asyncio.create_task(signing_refresh_loop())
            async with existing_lifespan(application):
                yield
        finally:
            if signing_task is not None:
                signing_task.cancel()
                with suppress(asyncio.CancelledError):
                    await signing_task
            try:
                await identity_link_verifier.aclose()
                await oidc.aclose()
            finally:
                await engine.dispose()

    app.router.lifespan_context = lifespan

    async def live() -> dict[str, str]:
        return {"status": "alive"}

    async def ready() -> JSONResponse:
        try:
            available = await native_authority_ready()
            if signing_resolver is not None:
                await refresh_managed_signing()
                available = available and signing_codec.enabled
        except (
            AppointmentSigningKeyringUnavailable,
            SQLAlchemyError,
            OSError,
            TimeoutError,
        ):
            available = False
        return JSONResponse(
            {"status": "ready" if available else "unavailable"},
            status_code=200 if available else 503,
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route("/health/live", live, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/ready", ready, methods=["GET"], include_in_schema=False)
    return app
