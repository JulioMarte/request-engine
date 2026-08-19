from collections.abc import AsyncIterator

import pytest_asyncio

from request_engine.platform.db.session import SessionFactory


@pytest_asyncio.fixture
async def session_factory(
    app_session_factory: SessionFactory,
) -> AsyncIterator[SessionFactory]:
    """Force the public first vertical through the application runtime role."""

    yield app_session_factory
