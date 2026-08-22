from __future__ import annotations

from typing import cast

import pytest
from fastapi import Request

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_http_surface import OPERATIONAL_HTTP_OPERATIONS, operational_keys

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})


class RejectAllResolver:
    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        raise AuthenticationRequired


def _operations(openapi: dict[str, object]) -> frozenset[tuple[str, str]]:
    paths = cast(dict[str, object], openapi["paths"])
    result: set[tuple[str, str]] = set()
    for path, item_value in paths.items():
        if not path.startswith("/v1/operations"):
            continue
        item = cast(dict[str, object], item_value)
        for method in item:
            if method.lower() in _HTTP_METHODS:
                result.add((method.upper(), path))
    return frozenset(result)


def _headers(openapi: dict[str, object], path: str, method: str) -> dict[str, bool]:
    paths = cast(dict[str, object], openapi["paths"])
    item = cast(dict[str, object], paths[path])
    operation = cast(dict[str, object], item[method.lower()])
    headers: dict[str, bool] = {}
    for value in cast(list[object], operation.get("parameters", [])):
        parameter = cast(dict[str, object], value)
        if parameter.get("in") == "header":
            headers[cast(str, parameter["name"]).lower()] = cast(bool, parameter.get("required", False))
    return headers


def _app(factory: SessionFactory):
    return create_operational_app(session_factory=factory, actor_resolver=RejectAllResolver())


@pytest.mark.e2e
@pytest.mark.postgres
def test_operational_surface_cannot_grow_without_classification(
    e2e_session_factory: SessionFactory,
) -> None:
    assert _operations(_app(e2e_session_factory).openapi()) == operational_keys()


@pytest.mark.e2e
@pytest.mark.postgres
def test_all_operational_mutations_require_idempotency_header(
    e2e_session_factory: SessionFactory,
) -> None:
    openapi = cast(dict[str, object], _app(e2e_session_factory).openapi())
    for operation in OPERATIONAL_HTTP_OPERATIONS:
        assert _headers(openapi, operation.path_template, operation.method).get("idempotency-key") is True


@pytest.mark.e2e
@pytest.mark.postgres
def test_operational_registry_has_unique_semantic_operations() -> None:
    names = [item.name for item in OPERATIONAL_HTTP_OPERATIONS]
    keys = [item.operation_key for item in OPERATIONAL_HTTP_OPERATIONS]
    assert len(names) == len(set(names))
    assert len(keys) == len(set(keys))
    assert all(path.startswith("/v1/operations") for _, path in keys)
