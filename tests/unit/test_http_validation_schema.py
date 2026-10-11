"""Generated clients must expect the same validation envelope as HTTP callers."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.platform.http.errors import ErrorEnvelope

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class ExampleBody(BaseModel):
    quantity: int = Field(ge=1)


@pytest.mark.asyncio
async def test_generated_validation_schema_matches_actual_sanitized_error() -> None:
    app = FastAPI()
    add_global_error_handlers(app)

    async def create(body: ExampleBody) -> dict[str, int]:
        return {"quantity": body.quantity}

    app.add_api_route("/example", create, methods=["POST"], operation_id="example_create")
    schema = app.openapi()
    declared = schema["paths"]["/example"]["post"]["responses"]["422"]
    assert declared["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert schema["components"]["schemas"]["ErrorEnvelope"]["required"] == ["error"]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/example", json={"quantity": "private-unusable-value"})
    assert response.status_code == 422
    error = ErrorEnvelope.model_validate(response.json()).error
    assert error.code == "validation_failed" and error.resolution == "fix_request"
    assert error.details["fields"]
    assert "private-unusable-value" not in response.text


def test_explicit_owner_validation_contract_is_not_overwritten() -> None:
    app = FastAPI()
    add_global_error_handlers(app)

    async def query() -> dict[str, bool]:
        return {"ok": True}

    owner_response = {
        "description": "Explicit owner protocol",
        "content": {"application/json": {"schema": {"type": "object"}}},
    }
    app.add_api_route("/example", query, methods=["GET"], responses={422: owner_response})
    assert app.openapi()["paths"]["/example"]["get"]["responses"]["422"] == owner_response
