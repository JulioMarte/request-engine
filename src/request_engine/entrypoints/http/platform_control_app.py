from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import FastAPI, Request, Response

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.entrypoints.http.instance_setup import install_instance_setup_http
from request_engine.entrypoints.http.native_auth import create_native_auth_router
from request_engine.entrypoints.http.native_runtime import (
    build_native_auth_runtime,
    resolve_webauthn_decoy_key,
)
from request_engine.modules.tenancy.api.identity_recovery import install_identity_recovery_http
from request_engine.modules.tenancy.api.native_platform_provisioning import (
    install_native_platform_provisioning_http,
)
from request_engine.modules.tenancy.api.platform_native_identity_management import (
    install_native_identity_management_http,
)
from request_engine.modules.tenancy.api.platform_owner_management import (
    install_platform_owner_management_http,
)
from request_engine.modules.tenancy.api.platform_provisioner_management import (
    install_native_platform_provisioner_management_http,
)
from request_engine.platform.db.instance_setup_store import PostgresInstanceSetupStore
from request_engine.platform.db.native_recovery_address_store import (
    PostgresNativeRecoveryAddressStore,
)
from request_engine.platform.db.recovery_code_store import PostgresRecoveryCodeStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.webauthn_store import PostgresWebAuthnStore
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.security.instance_setup import InstanceSetupService
from request_engine.platform.security.native_recovery_addresses import (
    NativeRecoveryAddressService,
    NativeRecoveryMessenger,
)
from request_engine.platform.security.native_webauthn_auth import NativeWebAuthnAuthService
from request_engine.platform.security.native_webauthn_login import NativeWebAuthnLoginService
from request_engine.platform.security.recovery_codes import NativeRecoveryCodeService
from request_engine.platform.security.webauthn import WebAuthnPolicy

_DEFAULT_WEBAUTHN_POLICY = WebAuthnPolicy(
    rp_id="localhost",
    rp_name="Request Engine",
    allowed_origins=frozenset({"https://localhost"}),
)


def create_platform_control_app(
    *,
    auth_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_write_session_factory: SessionFactory,
    native_authority_id: UUID,
    recovery_delivery: RecoverySecretDelivery | None = None,
    native_recovery_messenger: NativeRecoveryMessenger | None = None,
    webauthn_policy: WebAuthnPolicy | None = None,
    webauthn_decoy_key: bytes | None = None,
) -> FastAPI:
    """Explicit private control-plane composition; caller owns pool lifecycles.

    No tenant business router or external identity service is required. The
    ordinary native API factory never installs this separate control-plane API.
    """
    runtime = build_native_auth_runtime(
        auth_session_factory, platform_session_factory=platform_read_session_factory
    )
    if runtime.platform_actor_resolver is None:
        raise RuntimeError("Platform control requires an explicit authority read connection")
    webauthn_store = PostgresWebAuthnStore(auth_session_factory)
    webauthn_auth = NativeWebAuthnAuthService(
        policy=webauthn_policy or _DEFAULT_WEBAUTHN_POLICY,
        store=webauthn_store,
    )
    webauthn_login = NativeWebAuthnLoginService(
        webauthn=webauthn_auth,
        identities=webauthn_store,
        decoy_key=resolve_webauthn_decoy_key(webauthn_decoy_key),
    )
    recovery_codes = NativeRecoveryCodeService(
        store=PostgresRecoveryCodeStore(auth_session_factory)
    )
    app = FastAPI(title="Request Engine platform control", version="1.0.0")

    async def uncached_control_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.middleware("http")(uncached_control_response)
    add_global_error_handlers(app)
    app.include_router(
        create_native_auth_router(
            service=runtime.service,
            authenticator=runtime.authenticator,
            identity_authority_id=native_authority_id,
            webauthn_login=webauthn_login,
            webauthn_auth=webauthn_auth,
            recovery_codes=recovery_codes,
            recovery_addresses=NativeRecoveryAddressService(
                store=PostgresNativeRecoveryAddressStore(auth_session_factory),
                messenger=native_recovery_messenger,
            ),
            allow_identity_enrollment=False,
        )
    )
    install_native_platform_provisioning_http(
        app,
        session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
        native_authority_id=native_authority_id,
    )
    install_native_platform_provisioner_management_http(
        app,
        read_session_factory=platform_read_session_factory,
        write_session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
    )
    install_platform_owner_management_http(
        app,
        write_session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
        native_authority_id=native_authority_id,
    )
    install_identity_recovery_http(
        app,
        read_session_factory=platform_read_session_factory,
        write_session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
        delivery=recovery_delivery,
    )
    install_native_identity_management_http(
        app,
        read_session_factory=platform_read_session_factory,
        write_session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
        native_auth_service=runtime.service,
        native_authority_id=native_authority_id,
    )
    install_instance_setup_http(
        app,
        service=InstanceSetupService(
            store=PostgresInstanceSetupStore(platform_write_session_factory),
            webauthn=webauthn_auth,
            recovery_codes=recovery_codes,
        ),
    )
    return app
