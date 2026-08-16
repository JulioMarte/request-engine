from collections.abc import AsyncIterator

import pytest_asyncio

from request_engine.platform.db.session import SessionFactory


@pytest_asyncio.fixture
async def delivery_session_factory(
    app_session_factory: SessionFactory,
) -> AsyncIterator[SessionFactory]:
    """Delivery authoritative writes use the production request_engine_app boundary."""

    yield app_session_factory
