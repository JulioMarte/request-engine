from typing import cast

import pytest
from fastapi import APIRouter, FastAPI

from request_engine.platform.http.capability_routes import add_capability_route


def _operation(app: FastAPI, path: str, method: str) -> dict[str, object]:
    paths = cast(dict[str, object], app.openapi()["paths"])
    path_item = cast(dict[str, object], paths[path])
    return cast(dict[str, object], path_item[method.lower()])


def test_capability_route_projects_operation_policy_without_a_second_registry() -> None:
    router = APIRouter()

    async def readiness() -> dict[str, bool]:
        return {"ready": True}

    add_capability_route(
        router,
        "/v1/onboarding/readiness-probe",
        readiness,
        capability="onboarding.read",
        methods=["GET"],
        operation_id="onboarding_readiness_probe",
        owner="onboarding",
        tool_audiences=("operator", "admin"),
    )
    app = FastAPI()
    app.include_router(router)

    operation = _operation(app, "/v1/onboarding/readiness-probe", "GET")
    assert operation["operationId"] == "onboarding_readiness_probe"
    assert operation["x-request-engine-operation-id"] == operation["operationId"]
    assert operation["x-request-engine-owner"] == "onboarding"
    assert operation["x-request-engine-capability"] == "onboarding.read"
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"
    assert operation["x-request-engine-exposure"] == "operator"
    assert operation["x-request-engine-tool-name"] == "onboarding_readiness_probe"
    assert operation["x-request-engine-tool-audiences"] == ["operator", "admin"]


def test_tool_projection_requires_explicit_operation_identity_and_owner() -> None:
    router = APIRouter()

    async def readiness() -> dict[str, bool]:
        return {"ready": True}

    with pytest.raises(ValueError, match="explicit stable operation_id"):
        add_capability_route(
            router,
            "/probe",
            readiness,
            capability="onboarding.read",
            methods=["GET"],
            owner="onboarding",
            tool_audiences=("operator",),
        )

    with pytest.raises(ValueError, match="explicit or inferable owner"):
        add_capability_route(
            router,
            "/probe",
            readiness,
            capability="onboarding.read",
            methods=["GET"],
            operation_id="onboarding_readiness_probe",
            tool_audiences=("operator",),
        )


def test_tool_projection_uses_closed_audience_and_mcp_safe_name_vocabulary() -> None:
    router = APIRouter()

    async def readiness() -> dict[str, bool]:
        return {"ready": True}

    with pytest.raises(ValueError, match="unknown tool audiences"):
        add_capability_route(
            router,
            "/probe",
            readiness,
            capability="onboarding.read",
            methods=["GET"],
            operation_id="onboarding_readiness_probe",
            owner="onboarding",
            tool_audiences=("superuser",),
        )

    with pytest.raises(ValueError, match="tool_name must be"):
        add_capability_route(
            router,
            "/probe",
            readiness,
            capability="onboarding.read",
            methods=["GET"],
            operation_id="onboarding_readiness_probe",
            owner="onboarding",
            tool_name="onboarding readiness!",
            tool_audiences=("operator",),
        )


def test_tool_metadata_never_replaces_owner_capability_metadata() -> None:
    router = APIRouter()

    async def readiness() -> dict[str, bool]:
        return {"ready": True}

    add_capability_route(
        router,
        "/probe",
        readiness,
        capability="onboarding.read",
        methods=["GET"],
        operation_id="onboarding_readiness_probe",
        owner="onboarding",
        tool_name="onboarding.readiness.get",
        tool_audiences=("operator", "admin"),
    )
    app = FastAPI()
    app.include_router(router)
    operation = _operation(app, "/probe", "GET")

    assert operation["x-request-engine-tool-name"] == "onboarding.readiness.get"
    assert operation["x-request-engine-capability"] == "onboarding.read"
    assert operation["x-request-engine-owner"] == "onboarding"
