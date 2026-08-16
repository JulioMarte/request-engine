from __future__ import annotations

from typing import cast

import pytest
from fastapi import Request

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .http_surface import PUBLIC_HTTP_OPERATIONS, operation_keys

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_SIGNING_KEY = b"request-engine-e2e-contract-signing-key"


class RejectAllResolver:
    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        raise AuthenticationRequired


def _public_operations(openapi: dict[str, object]) -> frozenset[tuple[str, str]]:
    paths_value = openapi.get("paths")
    assert isinstance(paths_value, dict)
    paths = cast(dict[str, object], paths_value)
    operations: set[tuple[str, str]] = set()
    for path, path_item_value in paths.items():
        assert isinstance(path_item_value, dict)
        path_item = cast(dict[str, object], path_item_value)
        if not path.startswith("/v1/"):
            continue
        for method in path_item:
            if method.lower() in _HTTP_METHODS:
                operations.add((method.upper(), path))
    return frozenset(operations)


def _operation_contract(openapi: dict[str, object], *, path: str, method: str) -> dict[str, object]:
    paths_value = openapi.get("paths")
    assert isinstance(paths_value, dict)
    paths = cast(dict[str, object], paths_value)
    path_value = paths[path]
    assert isinstance(path_value, dict)
    operation_value = cast(dict[str, object], path_value)[method.lower()]
    assert isinstance(operation_value, dict)
    return cast(dict[str, object], operation_value)


def _header_parameters(operation_contract: dict[str, object]) -> dict[str, bool]:
    parameters_value = operation_contract.get("parameters", [])
    assert isinstance(parameters_value, list)
    headers: dict[str, bool] = {}
    for parameter_value in cast(list[object], parameters_value):
        assert isinstance(parameter_value, dict)
        parameter = cast(dict[str, object], parameter_value)
        if parameter.get("in") != "header":
            continue
        name = parameter.get("name")
        required = parameter.get("required", False)
        assert isinstance(name, str)
        assert isinstance(required, bool)
        headers[name.lower()] = required
    return headers


def _app(e2e_session_factory: SessionFactory):
    return create_app(
        session_factory=e2e_session_factory,
        actor_resolver=RejectAllResolver(),
        appointment_option_signing_key=_SIGNING_KEY,
    )


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_public_http_surface_cannot_grow_without_e2e_classification(
    e2e_session_factory: SessionFactory,
) -> None:
    assert _public_operations(_app(e2e_session_factory).openapi()) == operation_keys()


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_idempotency_registry_matches_required_openapi_headers(
    e2e_session_factory: SessionFactory,
) -> None:
    openapi = cast(dict[str, object], _app(e2e_session_factory).openapi())
    for operation in PUBLIC_HTTP_OPERATIONS:
        contract = _operation_contract(
            openapi, path=operation.path_template, method=operation.method
        )
        headers = _header_parameters(contract)
        if operation.idempotency_required:
            assert headers.get("idempotency-key") is True, operation.name
        else:
            assert "idempotency-key" not in headers, operation.name


@pytest.mark.e2e
@pytest.mark.postgres
def test_public_http_operation_registry_has_complete_test_metadata() -> None:
    names = [operation.name for operation in PUBLIC_HTTP_OPERATIONS]
    keys = [operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS]
    assert len(names) == len(set(names))
    assert len(keys) == len(set(keys))
    assert len(PUBLIC_HTTP_OPERATIONS) == 24
    discovery = [operation for operation in PUBLIC_HTTP_OPERATIONS if operation.capability is None]
    assert [operation.name for operation in discovery] == ["capabilities.list"]
    for operation in PUBLIC_HTTP_OPERATIONS:
        assert operation.probe.path.startswith("/v1/")
        if operation.method == "POST":
            assert operation.mutates
            assert operation.idempotency_required
        else:
            assert operation.method == "GET"
            assert not operation.mutates
            assert not operation.idempotency_required
