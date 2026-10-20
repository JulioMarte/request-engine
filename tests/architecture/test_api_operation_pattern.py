from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.mcp_tools import project_tool
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.operation_risk import OperationRiskClass


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


def test_mounted_tool_projections_are_operational_classified_and_mcp_mappable() -> None:
    """Every projected tool names one explicit owner operation the MCP gateway can map.

    Protects ADR 0018: a tool is only a projection of an explicit, owner-identified,
    agent-admissible operation (OPERATIONAL plane, classified risk that is not an
    authority change); the gateway must never guess or widen its input contract.
    """

    engine = create_postgres_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    app = create_native_app(
        session_factory=create_session_factory(engine),
        native_identity_authority_id=uuid4(),
        appointment_option_signing_key=b"tool-projection-architecture-key-01",
    )
    openapi = app.openapi()
    projected: dict[str, str] = {}
    for path, path_item in cast(dict[str, dict[str, dict[str, Any]]], openapi["paths"]).items():
        for method, operation in path_item.items():
            tool_name = operation.get("x-request-engine-tool-name")
            if tool_name is None:
                continue
            operation_id = operation["operationId"]
            assert operation["x-request-engine-operation-id"] == operation_id
            assert operation.get("x-request-engine-owner"), operation_id
            assert set(operation["x-request-engine-tool-audiences"]) <= {
                "public",
                "operator",
                "admin",
                "system",
            }
            definition = capability_definition(operation["x-request-engine-capability"])
            assert definition is not None and definition.runtime_available, operation_id
            assert definition.authority_plane is AuthorityPlane.OPERATIONAL, operation_id
            risk = definition.effective_risk_class
            assert risk is not None, f"{operation_id} has unclassified agent risk"
            assert risk is not OperationRiskClass.AUTHORITY_CHANGE, operation_id
            pointer = "/paths/" + path.replace("~", "~0").replace("/", "~1") + "/" + method
            assert project_tool(openapi, pointer, tool_name) is not None, operation_id
            assert tool_name not in projected, f"duplicate tool name {tool_name}"
            projected[tool_name] = operation_id
    assert projected, "the MCP gateway would expose no tools"
