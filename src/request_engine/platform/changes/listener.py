"""One dedicated PostgreSQL LISTEN connection per runtime process."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from importlib import import_module
from typing import Protocol, cast
from uuid import UUID

CHANGE_CHANNEL = "request_engine_changes"

_LOGGER = logging.getLogger(__name__)
_asyncpg = import_module("asyncpg")
_AsyncpgError = cast(type[Exception], _asyncpg.PostgresError)
_AsyncpgInterfaceError = cast(type[Exception], _asyncpg.InterfaceError)


class _ListenConnection(Protocol):
    async def add_listener(
        self, channel: str, callback: Callable[[object, int, str, str], None]
    ) -> None: ...

    def add_termination_listener(self, callback: Callable[[object], None]) -> None: ...

    async def execute(self, query: str) -> str: ...

    def is_closed(self) -> bool: ...

    async def close(self) -> None: ...


ListenConnect = Callable[[str], Awaitable[_ListenConnection]]


async def _asyncpg_connect(dsn: str) -> _ListenConnection:
    connect = cast(Callable[..., Awaitable[object]], _asyncpg.connect)
    connection = await connect(
        dsn,
        timeout=5,
        server_settings={"application_name": "request_engine_change_feed"},
    )
    return cast(_ListenConnection, connection)


def parse_signal(payload: str) -> tuple[UUID, int] | None:
    """Decode ``<organization_id>:<xid8>``; anything else is ignored."""

    organization, separator, xid = payload.partition(":")
    if not separator or not xid.isdigit():
        return None
    try:
        return UUID(organization), int(xid)
    except ValueError:
        return None


class ChangeSignalListener:
    """Hold LISTEN on one autocommit connection, reconnecting with backoff.

    The connection never opens a transaction, takes no locks and runs only
    ``LISTEN`` and a periodic liveness ``SELECT 1``. Signals are wake-ups, not
    data: a lost signal only delays a delivery because the feed reads by
    snapshot delta and every (re)connection re-reads all tracked organizations.
    """

    def __init__(
        self,
        *,
        dsn: str,
        on_signal: Callable[[UUID, int], None],
        on_connected: Callable[[], None],
        connect: ListenConnect | None = None,
        liveness_seconds: float = 15.0,
        reconnect_min_seconds: float = 0.5,
        reconnect_max_seconds: float = 30.0,
    ) -> None:
        self._dsn = dsn
        self._on_signal = on_signal
        self._on_connected = on_connected
        self._connect = connect or _asyncpg_connect
        self._liveness_seconds = liveness_seconds
        self._reconnect_min = reconnect_min_seconds
        self._reconnect_max = reconnect_max_seconds
        self.ready = asyncio.Event()

    async def run(self, stop: asyncio.Event) -> None:
        delay = self._reconnect_min
        while not stop.is_set():
            connection: _ListenConnection | None = None
            terminated = asyncio.Event()
            try:
                connection = await self._connect(self._dsn)
                connection.add_termination_listener(
                    lambda _connection, event=terminated: event.set()
                )
                await connection.add_listener(CHANGE_CHANNEL, self._notification)
                self.ready.set()
                delay = self._reconnect_min
                self._on_connected()
                await self._hold(connection, terminated, stop)
            except (OSError, TimeoutError, _AsyncpgError, _AsyncpgInterfaceError) as exc:
                _LOGGER.warning("change feed LISTEN unavailable: %s", type(exc).__name__)
            finally:
                self.ready.clear()
                if connection is not None and not connection.is_closed():
                    with suppress(Exception):
                        await connection.close()
            if stop.is_set():
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
            delay = min(delay * 2, self._reconnect_max)

    async def _hold(
        self,
        connection: _ListenConnection,
        terminated: asyncio.Event,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            waiters = (
                asyncio.ensure_future(terminated.wait()),
                asyncio.ensure_future(stop.wait()),
            )
            try:
                done, _ = await asyncio.wait(
                    waiters,
                    timeout=self._liveness_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for waiter in waiters:
                    waiter.cancel()
            if terminated.is_set() or connection.is_closed():
                raise OSError("LISTEN connection terminated")
            if done:
                return
            async with asyncio.timeout(5):
                await connection.execute("SELECT 1")

    def _notification(self, _connection: object, _pid: int, channel: str, payload: str) -> None:
        if channel != CHANGE_CHANNEL:
            return
        signal = parse_signal(payload)
        if signal is not None:
            self._on_signal(*signal)
