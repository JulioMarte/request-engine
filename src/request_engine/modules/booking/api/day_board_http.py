from fastapi import FastAPI

from request_engine.modules.booking.adapters.db.day_board_reader import PostgresDayBoardReader
from request_engine.modules.booking.api.day_board_routes import create_day_board_router
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_day_board_http(
    app: FastAPI,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    app.include_router(
        create_day_board_router(
            reader=PostgresDayBoardReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
