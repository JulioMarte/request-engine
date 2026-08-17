from collections.abc import Callable
from typing import Any, cast

import httpx


class DropFirstMatchingResponseTransport(httpx.AsyncBaseTransport):
    """Let ASGI finish/commit, then drop one selected response before the client sees it."""

    def __init__(
        self,
        app: object,
        *,
        matches: Callable[[httpx.Request], bool],
    ) -> None:
        self._inner = httpx.ASGITransport(app=cast(Any, app))
        self._matches = matches
        self._dropped = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if not self._dropped and self._matches(request):
            self._dropped = True
            await response.aclose()
            raise httpx.ReadError(
                "simulated response loss after committed command",
                request=request,
            )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
