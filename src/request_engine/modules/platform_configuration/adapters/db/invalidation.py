from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import asyncpg
from sqlalchemy.engine import make_url

from request_engine.platform.worker.runtime import WorkerItemOutcome

_CHANNEL = "request_engine_platform_configuration"


class PlatformConfigurationInvalidationRuntime:
    """Accelerate cache invalidation with PostgreSQL LISTEN/NOTIFY.

    Correctness does not depend on this stream: runtime resolvers periodically
    re-read PostgreSQL ACTIVE state. A dropped notification therefore increases
    convergence latency only.
    """

    def __init__(
        self,
        *,
        database_url: str,
        invalidate: Callable[[str], None],
        reconnect_delay_seconds: float = 1.0,
        connect: Callable[..., Awaitable[asyncpg.Connection]] | None = None,
    ) -> None:
        if reconnect_delay_seconds <= 0 or reconnect_delay_seconds > 30:
            raise ValueError("reconnect delay must be > 0 and <= 30 seconds")
        url = make_url(database_url)
        if not url.username or not url.host or not url.database:
            raise ValueError("worker database URL must identify PostgreSQL login and endpoint")
        self._dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        self._invalidate = invalidate
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._connect = connect or asyncpg.connect

    async def run_once(self) -> tuple[WorkerItemOutcome, ...]:
        # LISTEN is a long-lived acceleration stream; bounded cycle work is done
        # by the resolver's PostgreSQL polling backstop instead.
        return ()

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            connection: asyncpg.Connection | None = None
            try:
                connection = await self._connect(self._dsn)
                await connection.add_listener(_CHANNEL, self._on_notification)
                await stop_event.wait()
            except (OSError, asyncpg.PostgresError):
                if stop_event.is_set():
                    return
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self._reconnect_delay_seconds,
                    )
                except TimeoutError:
                    pass
            finally:
                if connection is not None:
                    try:
                        await connection.remove_listener(_CHANNEL, self._on_notification)
                    except (asyncpg.PostgresError, RuntimeError):
                        pass
                    await connection.close()

    def _on_notification(
        self,
        _connection: asyncpg.Connection,
        _pid: int,
        channel: str,
        payload: str,
    ) -> None:
        if channel != _CHANNEL:
            return
        try:
            decoded: object = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(decoded, dict):
            return
        configuration_kind = cast(dict[str, object], decoded).get("configuration_kind")
        if isinstance(configuration_kind, str) and configuration_kind:
            self._invalidate(configuration_kind)
