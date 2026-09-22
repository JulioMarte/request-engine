"""Private native control-plane ASGI process with distinct least-privilege pools."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from request_engine.bootstrap.platform_secrets import build_platform_secret_store
from request_engine.bootstrap.recovery_delivery import (
    RecoveryDeliverySettings,
    build_native_recovery_messenger,
    build_recovery_secret_delivery,
)
from request_engine.bootstrap.settings import PlatformControlSettings
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.modules.tenancy.api import NATIVE_INITIAL_CONTROLLER_POLICY
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.webauthn import WebAuthnPolicy

_READ = (
    "request_platform.read_principal_authority(uuid)",
    "request_platform.read_platform_provisioners(uuid,uuid,integer)",
    "request_platform.read_identity_recovery_cases(uuid,uuid,integer)",
    "request_platform.read_native_identities(uuid,uuid,integer)",
    "request_platform.read_platform_configuration_revisions(text)",
    "request_platform.read_platform_secret_binding(uuid)",
)
_PROVISIONER = "request_platform.provision_native_tenant_provisioner(uuid,uuid,uuid,uuid,text)"
_RECOVERY_OPERATOR = "request_platform.provision_native_recovery_operator(uuid,uuid,uuid,uuid,text)"
_POLICY = "request_platform.select_initial_controller_policy(text)"
_ORGANIZATION = (
    "request_platform.provision_native_organization_root(uuid,text,text,uuid,uuid,uuid,uuid,text)"
)
_LIFECYCLE = (
    "request_platform.transition_native_platform_provisioner(uuid,text,bigint,text,text,text,text)",
    "request_platform.disable_native_identity(uuid,bigint,text,text,text,text)",
)
_RECOVERY = (
    "request_platform.create_identity_recovery_case(uuid,uuid,text,text,text,text,text)",
    "request_platform.approve_identity_recovery_case(uuid,bigint,text,text,text)",
    "request_platform.prepare_identity_recovery_issue(uuid,bigint,text,text)",
    "request_platform.issue_identity_recovery_case("
    "uuid,bigint,integer,uuid,bytea,text,timestamp with time zone,uuid,text,text,text,text)",
    "request_platform.revoke_identity_recovery_case(uuid,bigint,text,text,text)",
)
_OWNER = (
    "request_platform.transition_native_platform_owner(uuid,text,bigint,text,text,text,text)",
    "request_platform.create_platform_owner_invitation("
    "uuid,bytea,text,timestamp with time zone,text,text,text)",
    "request_platform.enroll_platform_owner_invitation(bytea,uuid,uuid,text,text)",
    "request_platform.activate_platform_owner_invitation(uuid,uuid,uuid,text,text)",
    "request_platform.revoke_platform_owner_invitation(uuid,text,text,text)",
)
_SETUP = (
    "request_platform.read_platform_instance()",
    "request_platform.create_setup_session(uuid,bytea,text,text,integer)",
    "request_platform.read_setup_session(bytea)",
    "request_platform.set_setup_pending_identity(uuid,uuid,text,text)",
    "request_platform.read_setup_pending_identity(uuid)",
    "request_platform.read_claim_readiness(uuid)",
    "request_platform.read_installation_claim(text,text)",
    "request_platform.read_installation_claim_intent_digest(text)",
    "request_platform.finalize_instance_claim(uuid,text,text,text,text,uuid)",
)
_PLATFORM_CONFIGURATION = (
    "request_platform.stage_platform_configuration(text,text,jsonb,uuid,text,text)",
    "request_platform.validate_platform_configuration_provider(text,bigint,bigint,integer,text,text)",
    "request_platform.activate_platform_configuration(text,bigint,bigint,text,text)",
    "request_platform.disable_platform_configuration(text,bigint,text,text)",
    "request_platform.prepare_platform_secret_mutation(text,text,text,uuid,bigint,integer,text,text)",
    "request_platform.mark_platform_secret_backend_applied(uuid,integer)",
    "request_platform.commit_platform_secret_mutation(uuid)",
    "request_platform.resolve_platform_provider_secret(uuid,text)",
    "request_platform.read_platform_provider_candidate(text,bigint,text)",
    "request_platform.record_platform_provider_test(text,bigint,bigint,integer,text,text,text,text)",
)


async def _verify_login(engine: AsyncEngine, group: str | None) -> None:
    async with engine.connect() as connection:
        allowed = await connection.scalar(
            text("""
            SELECT current_user = session_user AND r.rolcanlogin AND NOT (
                r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
            ) AND (CAST(:group_name AS text) IS NULL
                   OR pg_has_role(current_user, CAST(:group_name AS text), 'USAGE'))
              AND NOT EXISTS (
                  SELECT 1 FROM pg_roles other
                   WHERE other.oid <> r.oid
                     AND other.rolname IS DISTINCT FROM CAST(:group_name AS text)
                     AND pg_has_role(r.oid, other.oid, 'MEMBER')
              )
            FROM pg_roles r WHERE r.rolname = current_user
            """),
            {"group_name": group},
        )
        if allowed is not True:
            raise RuntimeError("Platform HTTP database login violates least-privilege requirements")
        if group == "request_engine_app":
            platform_access = await connection.scalar(
                text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname = 'request_platform'
                       AND has_function_privilege(current_user, p.oid, 'EXECUTE')
                )
                """)
            )
            if platform_access is not False:
                raise RuntimeError("App authentication connection has private platform authority")
            return
        direct_authority = await connection.scalar(
            text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname LIKE 'request_%' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                   AND (has_table_privilege(current_user, c.oid,
                           'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                        OR has_any_column_privilege(current_user, c.oid,
                           'SELECT,INSERT,UPDATE,REFERENCES'))
            ) OR EXISTS (
                SELECT 1 FROM pg_namespace n WHERE n.nspname LIKE 'request_%'
                 AND has_schema_privilege(current_user, n.oid, 'CREATE')
            )
            """)
        )
        if direct_authority is not False:
            raise RuntimeError("Platform HTTP connections must use private functions, not tables")
        required = (
            _READ
            if group is None
            else (
                _PROVISIONER,
                _RECOVERY_OPERATOR,
                _ORGANIZATION,
                _POLICY,
                *_LIFECYCLE,
                *_RECOVERY,
                *_OWNER,
                *_SETUP,
                *_PLATFORM_CONFIGURATION,
            )
        )
        for function in required:
            if not await connection.scalar(
                text("SELECT has_function_privilege(current_user, :function, 'EXECUTE')"),
                {"function": function},
            ):
                raise RuntimeError("Platform HTTP connection lacks its required command surface")
        permitted = (
            [*_READ]
            if group is None
            else [*required, "request_platform.provision_tenant_provisioner(uuid,text,text)"]
        )
        extra_function = await connection.scalar(
            text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname LIKE 'request_%'
                   AND p.oid::regprocedure::text <> ALL(CAST(:permitted AS text[]))
                   AND has_function_privilege(current_user, p.oid, 'EXECUTE')
            )
            """),
            {"permitted": permitted},
        )
        if extra_function is not False:
            raise RuntimeError("Platform connection has authority beyond its explicit surface")
        if group == "request_platform_control":
            # Validate the owner-selected version through the same private surface
            # as provisioning. Only a transaction-local setting is touched; this
            # connection's transaction is rolled back on exit.
            await connection.execute(
                text("SELECT request_platform.select_initial_controller_policy(:policy)"),
                {"policy": NATIVE_INITIAL_CONTROLLER_POLICY},
            )


def create_app() -> FastAPI:
    settings = PlatformControlSettings.model_validate({})
    recovery_settings = RecoveryDeliverySettings()
    delivery = build_recovery_secret_delivery(recovery_settings)
    native_recovery_messenger = build_native_recovery_messenger(recovery_settings)
    platform_secret_store = build_platform_secret_store()
    engines = tuple(
        create_postgres_engine(url.get_secret_value())
        for url in (
            settings.database_url,
            settings.platform_read_database_url,
            settings.platform_control_database_url,
        )
    )
    # Avoid a mixed-database trust root. Deliberately require the same endpoint;
    # aliases must be normalized by the deployment configuration, not guessed.
    endpoints = {(engine.url.host, engine.url.port, engine.url.database) for engine in engines}
    if len(endpoints) != 1 or len({engine.url.username for engine in engines}) != 3:
        raise ValueError(
            "Platform HTTP requires three distinct logins on the same database endpoint"
        )
    app = create_platform_control_app(
        auth_session_factory=create_session_factory(engines[0]),
        platform_read_session_factory=create_session_factory(engines[1]),
        platform_write_session_factory=create_session_factory(engines[2]),
        native_authority_id=settings.native_identity_authority_id,
        recovery_delivery=delivery,
        native_recovery_messenger=native_recovery_messenger,
        platform_secret_store=platform_secret_store,
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
    )
    original_lifespan = app.router.lifespan_context

    async def ready_state() -> bool:
        async with asyncio.timeout(settings.database_probe_timeout_seconds):
            for engine, group in zip(
                engines, ("request_engine_app", None, "request_platform_control"), strict=True
            ):
                await _verify_login(engine, group)
            async with engines[0].connect() as connection:
                return (
                    await connection.scalar(
                        text("SELECT request_auth.is_native_authority_ready(:authority_id)"),
                        {"authority_id": settings.native_identity_authority_id},
                    )
                    is True
                )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        try:
            if not await ready_state():
                raise RuntimeError("Configured native identity authority is unavailable")
            async with original_lifespan(application):
                yield
        finally:
            await asyncio.gather(*(engine.dispose() for engine in engines))

    async def ready() -> JSONResponse:
        try:
            available = await ready_state()
        except (SQLAlchemyError, OSError, TimeoutError, RuntimeError):
            available = False
        return JSONResponse(
            {"status": "ready" if available else "unavailable"},
            status_code=200 if available else 503,
            headers={"Cache-Control": "no-store"},
        )

    async def live() -> dict[str, str]:
        return {"status": "alive"}

    app.router.lifespan_context = lifespan
    app.add_api_route("/health/ready", ready, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/live", live, methods=["GET"], include_in_schema=False)
    return app
