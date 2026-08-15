from collections.abc import AsyncIterator

import pytest_asyncio

from request_engine.platform.db.session import SessionFactory


@pytest_asyncio.fixture
async def session_factory(
    worker_session_factory: SessionFactory,
) -> AsyncIterator[SessionFactory]:
    """Force worker runtime tests through the production worker privilege boundary."""

    yield worker_session_factory
