from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


class PostgresNativeSessionToucher:
    """Record bounded Native-session activity through the least-privilege boundary."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def touch_native_session(self, *, session_id: UUID, min_interval_seconds: int) -> bool:
        async with self._session_factory() as session, session.begin():
            value = (
                await session.execute(
                    text(
                        """
                        SELECT request_auth.touch_native_session(
                            :session_id, :min_interval_seconds
                        )
                        """
                    ),
                    {
                        "session_id": session_id,
                        "min_interval_seconds": min_interval_seconds,
                    },
                )
            ).scalar_one()
        return bool(value)
