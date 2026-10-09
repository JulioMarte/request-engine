"""Bound transport admission before parsing or authoritative owner execution."""

import asyncio
import math
import os
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.security.http import request_correlation_id


@dataclass(frozen=True, slots=True)
class HttpRequestBudget:
    max_body_bytes: int = 1_048_576
    max_active_requests: int = 128
    max_active_authentication: int = 4
    max_authentication_per_minute: int = 120
    max_active_probes: int = 4
    body_timeout_seconds: float = 15

    def __post_init__(self) -> None:
        bounds = (
            (self.max_body_bytes, 16_777_216),
            (self.max_active_requests, 4096),
            (self.max_active_authentication, 64),
            (self.max_active_probes, 64),
            (self.body_timeout_seconds, 120),
        )
        if any(not 0 < value <= maximum for value, maximum in bounds):
            raise ValueError("HTTP request budgets must be positive and within deployment bounds")
        if (
            type(self.max_authentication_per_minute) is not int
            or not 1 <= self.max_authentication_per_minute <= 10_000
        ):
            raise ValueError("authentication rate limit must be an integer from 1 through 10000")

    @classmethod
    def from_environment(cls) -> "HttpRequestBudget":
        auth_rate_limit = os.environ.get("REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE", "120")
        if not re.fullmatch(r"[0-9]+", auth_rate_limit):
            raise ValueError(
                "REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE must be an exact integer"
            )
        return cls(
            max_body_bytes=int(os.environ.get("REQUEST_ENGINE_HTTP_MAX_BODY_BYTES", "1048576")),
            max_active_requests=int(
                os.environ.get("REQUEST_ENGINE_HTTP_MAX_ACTIVE_REQUESTS", "128")
            ),
            max_active_authentication=int(
                os.environ.get("REQUEST_ENGINE_HTTP_MAX_ACTIVE_AUTHENTICATION", "4")
            ),
            max_authentication_per_minute=int(auth_rate_limit),
            body_timeout_seconds=float(
                os.environ.get("REQUEST_ENGINE_HTTP_BODY_TIMEOUT_SECONDS", "15")
            ),
            max_active_probes=int(os.environ.get("REQUEST_ENGINE_HTTP_MAX_ACTIVE_PROBES", "4")),
        )


class RequestBudgetMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        budget: HttpRequestBudget,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.budget = budget
        self.clock = clock
        self.authentication_attempts: deque[float] = deque(
            maxlen=budget.max_authentication_per_minute
        )
        self.active = asyncio.Semaphore(budget.max_active_requests)
        self.authentication = asyncio.Semaphore(budget.max_active_authentication)
        self.probes = asyncio.Semaphore(budget.max_active_probes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Separate but bounded: readiness itself can acquire a DB connection.
        if scope["method"] == "GET" and scope["path"] in {"/health/live", "/health/ready"}:
            if self.probes.locked():
                await self._reject(scope, receive, send, 503, "request_capacity_exceeded", True)
                return
            await self.probes.acquire()
            try:
                await self._admitted(scope, receive, send)
            finally:
                self.probes.release()
            return
        path = str(scope["path"])
        authentication = path == "/auth/native" or path.startswith("/auth/native/")
        authentication_attempt = scope["method"] == "POST" and (
            authentication or path.startswith("/v1/setup/")
        )
        if authentication_attempt:
            retry_after = self._record_authentication_attempt()
            if retry_after is not None:
                await self._reject(
                    scope,
                    receive,
                    send,
                    429,
                    "request_rate_exceeded",
                    True,
                    retry_after_seconds=retry_after,
                )
                return
        if self.active.locked() or (authentication and self.authentication.locked()):
            await self._reject(scope, receive, send, 503, "request_capacity_exceeded", True)
            return
        # No queue: these acquires complete immediately without yielding when available.
        await self.active.acquire()
        if authentication:
            await self.authentication.acquire()
        try:
            await self._admitted(scope, receive, send)
        finally:
            if authentication:
                self.authentication.release()
            self.active.release()

    async def _admitted(self, scope: Scope, receive: Receive, send: Send) -> None:
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        length: int | None = None
        if lengths:
            try:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise ValueError("invalid length")
                length = int(lengths[0])
            except ValueError:
                await self._reject(scope, receive, send, 400, "invalid_content_length", False)
                return
            if length > self.budget.max_body_bytes:
                await self._reject(scope, receive, send, 413, "request_body_too_large", False)
                return
        body = bytearray()
        try:
            async with asyncio.timeout(self.budget.body_timeout_seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.budget.max_body_bytes:
                        await self._reject(
                            scope, receive, send, 413, "request_body_too_large", False
                        )
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self._reject(scope, receive, send, 408, "request_body_timeout", False)
            return
        # Validate the fully received ASGI body before any owner can execute.
        # A proxy/server may already enforce framing, but admission must not
        # depend on that deployment property or trust a caller-supplied length.
        if length is not None and len(body) != length:
            await self._reject(scope, receive, send, 400, "invalid_content_length", False)
            return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)

    def _record_authentication_attempt(self) -> int | None:
        now = self.clock()
        while self.authentication_attempts and now - self.authentication_attempts[0] >= 60:
            self.authentication_attempts.popleft()
        rejected = len(self.authentication_attempts) >= self.budget.max_authentication_per_minute
        # Rejected attempts are retained too, so repeated floods cannot gain admission
        # by filling only a separate rejection path. deque(maxlen=...) bounds memory.
        self.authentication_attempts.append(now)
        if not rejected:
            return None
        remaining = 60 - (now - self.authentication_attempts[0])
        return max(1, math.ceil(remaining))

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        code: str,
        retryable: bool,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        correlation = request_correlation_id(Request(scope))
        response = JSONResponse(
            ErrorEnvelope(
                error=ErrorBody(
                    code=code,
                    message=(
                        "Authentication request rate exceeded"
                        if code == "request_rate_exceeded"
                        else "Request exceeded the server transport budget"
                    ),
                    retryable=retryable,
                    resolution=(
                        ErrorResolution.RETRY_SAME_REQUEST
                        if retryable
                        else ErrorResolution.FIX_REQUEST
                    ),
                )
            ).model_dump(mode="json"),
            status_code=status,
            headers={
                "Cache-Control": "no-store",
                "X-Correlation-ID": str(correlation),
                **({"Retry-After": str(retry_after_seconds or 1)} if retryable else {}),
            },
        )
        await response(scope, receive, send)


def install_request_budget(app: FastAPI) -> None:
    app.state.http_request_budget_installed = True
    app.add_middleware(RequestBudgetMiddleware, budget=HttpRequestBudget.from_environment())
