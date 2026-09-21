from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import ValidationError

from request_engine.modules.platform_configuration.api.http import (
    StageConfigurationBody,
    install_platform_configuration_http,
    require_platform_configuration_step_up,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.freshness import (
    PhishingResistantAuthenticationRequired,
)
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver


def _actor(*, strong: bool) -> PlatformActorContext:
    return PlatformActorContext(
        principal_id=uuid4(),
        capabilities=frozenset(
            {
                "platform.configuration.read",
                "platform.configuration.stage",
                "platform.configuration.validate",
                "platform.configuration.activate",
                "platform.configuration.disable",
            }
        ),
        authority_revision=1,
        principal_kind=PrincipalKind.HUMAN,
        authentication_method="webauthn" if strong else "password",
        authentication_assurance=(
            AuthenticationAssurance.PHISHING_RESISTANT
            if strong
            else AuthenticationAssurance.SINGLE_FACTOR
        ),
        user_verified=strong,
        authenticated_at=datetime.now(UTC),
    )


def test_platform_configuration_http_registers_canonical_capability_surface() -> None:
    app = FastAPI()
    install_platform_configuration_http(
        app,
        read_session_factory=cast(SessionFactory, object()),
        write_session_factory=cast(SessionFactory, object()),
        actor_resolver=cast(PlatformActorResolver, object()),
    )

    operations: dict[str, tuple[str | None, str, frozenset[str]]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.operation_id is None:
            continue
        methods = frozenset[str]() if route.methods is None else frozenset(route.methods)
        operations[route.operation_id] = (
            cast(str | None, getattr(route, "request_engine_capability", None)),
            route.path,
            methods,
        )
    assert operations == {
        "platform_configuration_list": (
            "platform.configuration.read",
            "/v1/platform/configurations",
            frozenset({"GET"}),
        ),
        "platform_configuration_revision_list": (
            "platform.configuration.read",
            "/v1/platform/configurations/{configuration_kind}",
            frozenset({"GET"}),
        ),
        "platform_configuration_revision_get": (
            "platform.configuration.read",
            "/v1/platform/configurations/{configuration_kind}/revisions/{revision}",
            frozenset({"GET"}),
        ),
        "platform_secret_metadata_get": (
            "platform.configuration.read",
            "/v1/platform/secrets/{binding_id}",
            frozenset({"GET"}),
        ),
        "platform_configuration_stage": (
            "platform.configuration.stage",
            "/v1/platform/configurations/{configuration_kind}/revisions",
            frozenset({"POST"}),
        ),
        "platform_configuration_validate": (
            "platform.configuration.validate",
            "/v1/platform/configurations/{configuration_kind}/revisions/{revision}:validate",
            frozenset({"POST"}),
        ),
        "platform_configuration_activate": (
            "platform.configuration.activate",
            "/v1/platform/configurations/{configuration_kind}/revisions/{revision}:activate",
            frozenset({"POST"}),
        ),
        "platform_configuration_disable": (
            "platform.configuration.disable",
            "/v1/platform/configurations/{configuration_kind}/revisions/{revision}:disable",
            frozenset({"POST"}),
        ),
    }


@pytest.mark.parametrize(
    "configuration",
    [
        {"password": "plaintext"},
        {"smtp": {"api-key": "plaintext"}},
        {"nested": [{"token": "plaintext"}]},
    ],
)
def test_stage_payload_rejects_embedded_secret_material(
    configuration: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        StageConfigurationBody(
            provider_kind="smtp",
            configuration=configuration,
        )


def test_configuration_mutation_requires_phishing_resistant_step_up() -> None:
    with pytest.raises(PhishingResistantAuthenticationRequired):
        require_platform_configuration_step_up(_actor(strong=False))

    require_platform_configuration_step_up(_actor(strong=True))
