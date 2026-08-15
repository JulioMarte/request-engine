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


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_public_http_surface_cannot_grow_without_e2e_classification(
    e2e_session_factory: SessionFactory,
) -> None:
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=RejectAllResolver(),
    )

    assert _public_operations(app.openapi()) == operation_keys()


def test_public_http_operation_registry_has_complete_test_metadata() -> None:
    names = [operation.name for operation in PUBLIC_HTTP_OPERATIONS]
    keys = [operation.operation_key for operation in PUBLIC_HTTP_OPERATIONS]

    assert len(names) == len(set(names))
    assert len(keys) == len(set(keys))
    assert len(PUBLIC_HTTP_OPERATIONS) == 19

    for operation in PUBLIC_HTTP_OPERATIONS:
        assert operation.capability
        assert operation.probe.path.startswith("/v1/")
        if operation.method == "POST":
            assert operation.mutates
            assert operation.idempotency_required
        else:
            assert operation.method == "GET"
            assert not operation.mutates
            assert not operation.idempotency_required
