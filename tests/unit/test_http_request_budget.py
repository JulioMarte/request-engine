"""Transport admission rejects before owner execution, with no unbounded queue."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.platform.http.request_budget import (
    HttpRequestBudget,
    RequestBudgetMiddleware,
    install_request_budget,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.contract]


def _app(budget: HttpRequestBudget) -> tuple[FastAPI, list[bytes]]:
    app = FastAPI()
    calls: list[bytes] = []

    async def operation(request: Request) -> dict[str, int]:
        calls.append(await request.body())
        return {"bytes": len(calls[-1])}

    app.add_api_route("/operation", operation, methods=["POST"])
    app.add_middleware(RequestBudgetMiddleware, budget=budget)
    return app, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, "2", "100"])
async def test_oversized_body_never_reaches_owner_even_with_false_length(
    declared: str | None,
) -> None:
    app, calls = _app(HttpRequestBudget(max_body_bytes=8))

    async def stream() -> AsyncIterator[bytes]:
        yield b"12345"
        yield b"67890"

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/operation",
            content=stream(),
            headers={} if declared is None else {"Content-Length": declared},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_body_too_large"
        assert not response.json()["error"]["retryable"]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Correlation-ID"]
        accepted = await client.post("/operation", content=b"12345678")
        assert accepted.status_code == 200 and accepted.json() == {"bytes": 8}
    assert calls == [b"12345678"]


@pytest.mark.asyncio
@pytest.mark.parametrize("length", ["-1", "nonsense"])
async def test_malformed_length_is_safe_input_error(length: str) -> None:
    app, calls = _app(HttpRequestBudget())
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/operation", content=b"", headers={"Content-Length": length})
    assert response.status_code == 400 and calls == []
    assert "nonsense" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", ["0", "2", "7"])
async def test_inconsistent_length_never_executes_owner_and_releases_capacity(
    declared: str,
) -> None:
    app, calls = _app(HttpRequestBudget(max_body_bytes=8, max_active_requests=1))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        rejected = await client.post(
            "/operation", content=b"proof", headers={"Content-Length": declared}
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "invalid_content_length"
        assert not rejected.json()["error"]["retryable"]
        assert rejected.headers["Cache-Control"] == "no-store"
        assert rejected.headers["X-Correlation-ID"]
        assert calls == []
        accepted = await client.post("/operation", content=b"ok")
        assert accepted.status_code == 200
    assert calls == [b"ok"]


@pytest.mark.asyncio
async def test_stream_without_declared_length_remains_supported() -> None:
    app, calls = _app(HttpRequestBudget(max_body_bytes=8))

    async def stream() -> AsyncIterator[bytes]:
        yield b"1234"
        yield b"5678"

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        accepted = await client.post("/operation", content=stream())
    assert accepted.status_code == 200
    assert accepted.json() == {"bytes": 8}
    assert calls == [b"12345678"]


@pytest.mark.asyncio
@pytest.mark.parametrize("second", ["5", "6"])
async def test_duplicate_lengths_are_rejected_even_when_equal(second: str) -> None:
    app, calls = _app(HttpRequestBudget())
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/operation",
            content=b"proof",
            headers=[("Content-Length", "5"), ("Content-Length", second)],
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"
    assert calls == []


@pytest.mark.asyncio
async def test_disconnected_body_has_no_owner_effect_and_releases_admission() -> None:
    calls: list[Message] = []
    sent: list[Message] = []

    async def owner(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(await receive())

    middleware = RequestBudgetMiddleware(owner, budget=HttpRequestBudget(max_active_requests=1))
    scope: Scope = {"type": "http", "method": "POST", "path": "/operation", "headers": []}
    incoming: list[Message] = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(scope, receive, send)
    assert calls == [] and sent == []
    incoming.append({"type": "http.request", "body": b"complete", "more_body": False})
    await middleware(scope, receive, send)
    assert calls == [{"type": "http.request", "body": b"complete", "more_body": False}]
    assert sent == []


@pytest.mark.asyncio
async def test_slow_body_times_out_without_owner_effect_and_releases_admission() -> None:
    app, calls = _app(HttpRequestBudget(body_timeout_seconds=0.03, max_active_requests=1))
    stalled = asyncio.Event()

    async def stream() -> AsyncIterator[bytes]:
        yield b"1"
        await stalled.wait()
        yield b"2"

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/operation", content=stream())
        assert response.status_code == 408 and calls == []
        accepted = await client.post("/operation", content=b"ok")
        assert accepted.status_code == 200
    assert calls == [b"ok"]


@pytest.mark.asyncio
async def test_auth_saturation_does_not_queue_or_block_other_work_and_probes() -> None:
    app = FastAPI()
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0

    async def authentication() -> dict[str, bool]:
        nonlocal count
        count += 1
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        return {"ok": True}

    async def ordinary() -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route("/auth/native/login", authentication, methods=["POST"])
    app.add_api_route("/ordinary", ordinary, methods=["GET"])
    app.add_api_route("/health/live", ordinary, methods=["GET"])
    app.add_middleware(
        RequestBudgetMiddleware,
        budget=HttpRequestBudget(max_active_requests=2, max_active_authentication=1),
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        first = asyncio.create_task(client.post("/auth/native/login"))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            second = await client.post("/auth/native/login")
            assert second.status_code == 503
            assert second.json()["error"]["retryable"]
            assert second.headers["Retry-After"] == "1"
            assert count == 1
            assert (await client.get("/ordinary")).status_code == 200
            assert (await client.get("/health/live")).status_code == 200
        finally:
            release.set()
            await asyncio.wait_for(first, 5)
        assert (await client.post("/auth/native/login")).status_code == 200
    assert count == 2


@pytest.mark.parametrize(
    ("body", "auth", "timeout"),
    [(0, 4, 15.0), (8, 65, 15.0), (8, 4, float("nan"))],
)
def test_invalid_budget_never_disables_protection(body: int, auth: int, timeout: float) -> None:
    with pytest.raises(ValueError):
        HttpRequestBudget(
            max_body_bytes=body, max_active_authentication=auth, body_timeout_seconds=timeout
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/operation", "/health/ready"])
async def test_global_and_probe_capacity_are_bounded_and_released_on_cancel(path: str) -> None:
    app = FastAPI()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def operation() -> dict[str, bool]:
        nonlocal calls
        calls += 1
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        return {"ok": True}

    app.add_api_route(path, operation, methods=["GET"])
    app.add_middleware(
        RequestBudgetMiddleware,
        budget=HttpRequestBudget(max_active_requests=1, max_active_probes=1),
    )
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        first = asyncio.create_task(client.get(path))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            rejected = await client.get(path)
            assert rejected.status_code == 503 and calls == 1
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            assert (await client.get(path)).status_code == 200
            assert calls == 2
        finally:
            release.set()
            if not first.done():
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first


def test_environment_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_HTTP_MAX_ACTIVE_PROBES", "0")
    with pytest.raises(ValueError):
        HttpRequestBudget.from_environment()


def test_middleware_errors_are_discoverable_without_overwriting_owner_protocol() -> None:
    app = FastAPI()
    install_request_budget(app)
    add_global_error_handlers(app)

    async def operation() -> dict[str, bool]:
        return {"ok": True}

    explicit = {"description": "Owner-specific unavailability"}
    app.add_api_route("/operation", operation, methods=["GET"], responses={503: explicit})
    responses = app.openapi()["paths"]["/operation"]["get"]["responses"]
    for status in ("400", "408", "413"):
        assert responses[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorEnvelope"
        }
    assert responses["503"] == explicit
