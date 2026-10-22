"""``GET /v1/changes/stream``: invalidation-only Server-Sent Events (ADR 0020).

Trust-boundary composition, not a business owner: it authorizes each topic with
an existing owner read capability, then relays PII-free change signals from the
process-wide :class:`ChangeFeed`. Clients re-read through the owner reads.
Not tool-projected: a long-lived stream is a transport for UIs/BFFs, not an
agent-invocable owner operation.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from request_engine.entrypoints.http.change_topics import TOPIC_CAPABILITIES, ChangeTopicTable
from request_engine.entrypoints.http.errors import render_error_response
from request_engine.platform.changes.feed import (
    ChangeFeed,
    ChangeFeedSettings,
    ChangeFeedUnavailable,
)
from request_engine.platform.changes.hub import StreamLimitExceeded, Subscription
from request_engine.platform.changes.model import ChangeItem, StreamItem
from request_engine.platform.changes.postgres import PostgresChangeFeedReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.errors import ErrorBody, ErrorResolution
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver
from request_engine.platform.security.principal_authority import CapabilityRequired

STREAM_PATH = "/v1/changes/stream"
_UNAVAILABLE_RETRY_AFTER = "5"
_LIMIT_RETRY_AFTER = "10"


def build_change_feed(
    session_factory: SessionFactory, settings: ChangeFeedSettings | None = None
) -> ChangeFeed:
    """Create the process feed; LISTEN starts lazily on the first stream."""

    # Test compositions may pass a factory without a bound engine: the feed is
    # then simply unavailable (503) and the rest of the app is unaffected.
    engine = getattr(session_factory, "kw", {}).get("bind")
    dsn = ""
    url = getattr(engine, "url", None)
    if url is not None:
        dsn = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    return ChangeFeed(
        reader=PostgresChangeFeedReader(session_factory),
        catalog=ChangeTopicTable(),
        dsn=dsn,
        settings=settings or ChangeFeedSettings.from_environment(),
    )


def _format(event: str, data: dict[str, object], event_id: str | None = None) -> str:
    lines = [] if event_id is None else [f"id: {event_id}"]
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


def _frame(item: StreamItem) -> str:
    if isinstance(item, ChangeItem):
        return _format("change", item.event.data(), item.cursor)
    return _format("reset", {})


def _resolve_topics(raw: str | None, actor: ActorContext) -> frozenset[str] | JSONResponse:
    if raw is None:
        authorized = frozenset(
            topic for topic, capability in TOPIC_CAPABILITIES.items() if actor.allows(capability)
        )
        if not authorized:
            raise CapabilityRequired(next(iter(TOPIC_CAPABILITIES.values())))
        return authorized
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted({item for item in requested if item not in TOPIC_CAPABILITIES})
    if not requested or unknown:
        return render_error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorBody(
                code="unknown_change_topic",
                message="topics must name supported change topics",
                resolution=ErrorResolution.FIX_REQUEST,
                details={"unknown": unknown, "supported": sorted(TOPIC_CAPABILITIES)},
            ),
        )
    for topic in requested:
        # Fail closed: an unauthorized requested topic is never silently dropped.
        if not actor.allows(TOPIC_CAPABILITIES[topic]):
            raise CapabilityRequired(TOPIC_CAPABILITIES[topic])
    return frozenset(requested)


def _unavailable() -> JSONResponse:
    return render_error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorBody(
            code="change_feed_unavailable",
            message="the change feed is temporarily unavailable; poll owner reads",
            retryable=True,
            resolution=ErrorResolution.RETRY_SAME_REQUEST,
        ),
        headers={"Retry-After": _UNAVAILABLE_RETRY_AFTER, "Cache-Control": "no-store"},
    )


def _limited() -> JSONResponse:
    return render_error_response(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ErrorBody(
            code="change_stream_limit_exceeded",
            message="too many concurrent change streams for this principal",
            retryable=True,
            resolution=ErrorResolution.RETRY_SAME_REQUEST,
        ),
        headers={"Retry-After": _LIMIT_RETRY_AFTER, "Cache-Control": "no-store"},
    )


class _StreamSession:
    def __init__(
        self,
        *,
        feed: ChangeFeed,
        actor_resolver: ActorResolver,
        request: Request,
        actor: ActorContext,
        subscription: Subscription,
        replay: Sequence[StreamItem],
    ) -> None:
        self._feed = feed
        self._actor_resolver = actor_resolver
        self._request = request
        self._actor = actor
        self._subscription = subscription
        self._replay = replay

    async def _still_authorized(self) -> bool:
        try:
            current = await self._actor_resolver.resolve_actor(self._request)
        except Exception:  # any resolution failure ends the stream: fail closed
            return False
        return (
            current.organization_id == self._actor.organization_id
            and current.principal_id == self._actor.principal_id
            and all(
                current.allows(TOPIC_CAPABILITIES[topic]) for topic in self._subscription.topics
            )
        )

    async def frames(self) -> AsyncIterator[str]:
        settings = self._feed.settings
        loop = asyncio.get_running_loop()
        try:
            yield f"retry: {settings.retry_milliseconds}\n\n"
            for item in self._replay:
                yield _frame(item)
            last_sent = loop.time()
            next_recheck = last_sent + settings.authority_recheck_seconds
            while True:
                now = loop.time()
                wait = min(
                    settings.heartbeat_seconds - (now - last_sent),
                    next_recheck - now,
                )
                item: StreamItem | None = None
                if wait > 0:
                    try:
                        async with asyncio.timeout(wait):
                            item = await self._subscription.queue.get()
                    except TimeoutError:
                        item = None
                now = loop.time()
                if now >= next_recheck:
                    if not await self._still_authorized():
                        return
                    next_recheck = loop.time() + settings.authority_recheck_seconds
                if item is not None:
                    yield _frame(item)
                    last_sent = loop.time()
                elif now - last_sent >= settings.heartbeat_seconds:
                    yield _format("heartbeat", {})
                    last_sent = loop.time()
        finally:
            self._feed.unsubscribe(self._subscription)


def create_change_stream_router(*, feed: ChangeFeed, actor_resolver: ActorResolver) -> APIRouter:
    router = APIRouter(tags=["changes"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def changes_stream(
        request: Request,
        current: Annotated[ActorContext, Depends(actor)],
        topics: Annotated[str | None, Query(description="Comma-separated topics.")] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse | JSONResponse:
        resolved = _resolve_topics(topics, current)
        if isinstance(resolved, JSONResponse):
            return resolved
        try:
            await feed.ensure_started()
            subscription = await feed.subscribe(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                topics=resolved,
            )
        except ChangeFeedUnavailable:
            return _unavailable()
        except StreamLimitExceeded:
            return _limited()
        except (SQLAlchemyError, OSError, TimeoutError):
            return _unavailable()
        try:
            replay = [] if last_event_id is None else await feed.replay(subscription, last_event_id)
        except (SQLAlchemyError, OSError, TimeoutError):
            feed.unsubscribe(subscription)
            return _unavailable()
        except BaseException:
            feed.unsubscribe(subscription)
            raise
        session = _StreamSession(
            feed=feed,
            actor_resolver=actor_resolver,
            request=request,
            actor=current,
            subscription=subscription,
            replay=replay,
        )
        return StreamingResponse(
            session.frames(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    router.add_api_route(
        STREAM_PATH,
        changes_stream,
        methods=["GET"],
        operation_id="changes_stream",
        response_model=None,
        summary="Stream invalidation signals for authorized topics",
        responses={
            200: {
                "description": "Server-Sent Events: change, heartbeat, reset.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            },
            403: {"description": "A requested (or every) topic is not authorized."},
            422: {"description": "Unknown topic."},
            429: {"description": "Per-principal concurrent stream limit; see Retry-After."},
            503: {"description": "Change feed unavailable; poll owner reads."},
        },
        openapi_extra={
            "x-request-engine-operation-id": "changes_stream",
            "x-request-engine-owner": "platform",
            "x-request-engine-kind": "query",
            "x-request-engine-idempotency": "none",
            "x-request-engine-topic-capabilities": dict(TOPIC_CAPABILITIES),
        },
    )
    return router


__all__ = ["STREAM_PATH", "build_change_feed", "create_change_stream_router"]
