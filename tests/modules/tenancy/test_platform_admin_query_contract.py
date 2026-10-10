from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.api.platform_native_identity_management import (
    install_native_identity_management_http,
)
from request_engine.modules.tenancy.api.platform_owner_reads import (
    install_platform_owner_reads_http,
)
from request_engine.modules.tenancy.api.platform_provisioner_management import (
    install_native_platform_provisioner_management_http,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.platform_context import PlatformActorContext

pytestmark = [pytest.mark.contract, pytest.mark.adversarial]


class Resolver:
    async def resolve_platform_actor(self, request: Request) -> PlatformActorContext:
        return PlatformActorContext(
            principal_id=uuid4(),
            principal_kind=PrincipalKind.HUMAN,
            capabilities=frozenset(
                {
                    "platform.identity.read",
                    "platform.identity.provision",
                    "platform.owner.read",
                    "platform.provisioner.read",
                }
            ),
            authority_revision=1,
        )


def _app() -> FastAPI:
    app = FastAPI()
    factory = cast(SessionFactory, None)
    resolver = Resolver()
    install_native_identity_management_http(
        app,
        read_session_factory=factory,
        write_session_factory=factory,
        actor_resolver=resolver,
        native_auth_service=cast(NativeHumanAuthService, None),
        native_authority_id=uuid4(),
    )
    install_native_platform_provisioner_management_http(
        app,
        read_session_factory=factory,
        write_session_factory=factory,
        actor_resolver=resolver,
    )
    install_platform_owner_reads_http(app, read_session_factory=factory, actor_resolver=resolver)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/v1/platform/native-identities",
        "/v1/platform/provisioners",
        "/v1/platform/owners",
        "/v1/platform/owner-invitations",
    ],
)
async def test_unknown_admin_query_fields_are_rejected_before_reader(path: str) -> None:
    # A reader invocation would fail: no session factory is provided.
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="https://test") as client:
        response = await client.get(path, params={"organization_id": str(uuid4())})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_native_provision_requires_key_before_owner_command() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="https://test") as client:
        response = await client.post(
            "/v1/platform/native-identities",
            json={
                "login_handle": "new@example.test",
                "password": "a business plausible password",
            },
        )
    assert response.status_code == 422


def test_private_admin_queries_publish_security_and_secret_free_owner_views() -> None:
    schema = _app().openapi()
    for path in (
        "/v1/platform/native-identities",
        "/v1/platform/provisioners",
        "/v1/platform/owners",
        "/v1/platform/owner-invitations",
    ):
        assert schema["paths"][path]["get"]["security"] == [{"NativeSessionBearer": []}]
    fields = schema["components"]["schemas"]["OwnerInvitationView"]["properties"]
    assert {"status", "revision", "expires_at", "expired", "native_identity_id"} <= set(fields)
    assert not {"invitation_token", "token_digest", "token_fingerprint", "verifier"} & set(fields)
