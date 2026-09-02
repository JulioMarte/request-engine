import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class AsyncTwoPartyBarrier:
    def __init__(self) -> None:
        self._arrived = 0
        self._release = asyncio.Event()
        self._guard = asyncio.Lock()

    async def wait(self) -> None:
        async with self._guard:
            self._arrived += 1
            if self._arrived == 2:
                self._release.set()
        await self._release.wait()


def gated_lock(
    barrier: AsyncTwoPartyBarrier,
    original: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        await barrier.wait()
        return await original(*args, **kwargs)

    return wrapped
