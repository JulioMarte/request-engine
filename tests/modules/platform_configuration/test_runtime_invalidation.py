from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest

from request_engine.modules.platform_configuration.adapters.db.invalidation import (
    PlatformConfigurationInvalidationRuntime,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.callback: Callable[..., object] | None = None
        self.closed = False

    async def add_listener(self, channel: str, callback: Callable[..., object]) -> None:
        assert channel == "request_engine_platform_configuration"
        self.callback = callback

    async def remove_listener(self, channel: str, callback: Callable[..., object]) -> None:
        assert channel == "request_engine_platform_configuration"
        assert callback == self.callback

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_invalidation_runtime_routes_configuration_kind_and_stops_cleanly() -> None:
    connection = _FakeConnection()
    invalidated: list[str] = []
    stop = asyncio.Event()

    async def connect(_dsn: str) -> Any:
        return connection

    runtime = PlatformConfigurationInvalidationRuntime(
        database_url="postgresql+asyncpg://worker:secret@db.example.test/request_engine",
        invalidate=invalidated.append,
        connect=cast(Any, connect),
    )
    task = asyncio.create_task(runtime.run_forever(stop))

    for _ in range(20):
        if connection.callback is not None:
            break
        await asyncio.sleep(0)
    assert connection.callback is not None

    connection.callback(
        cast(Any, connection),
        42,
        "request_engine_platform_configuration",
        '{"configuration_kind":"email.delivery","revision":9}',
    )
    connection.callback(
        cast(Any, connection),
        42,
        "request_engine_platform_configuration",
        "not-json",
    )

    stop.set()
    await task

    assert invalidated == ["email.delivery"]
    assert connection.closed


@pytest.mark.asyncio
async def test_invalidation_runtime_run_once_is_inert_acceleration_stream() -> None:
    runtime = PlatformConfigurationInvalidationRuntime(
        database_url="postgresql+asyncpg://worker:secret@db.example.test/request_engine",
        invalidate=lambda _kind: None,
        connect=cast(Any, object()),
    )
    assert await runtime.run_once() == ()
