from fastapi import FastAPI

from request_engine.modules.booking.contracts.appointment_options import AppointmentOptionCodec
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.modules.discovery.adapters.db.candidate_reader import PostgresDiscoveryCandidateReader
from request_engine.modules.discovery.api.router import create_router
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.platform_discovery import PlatformDiscoveryActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: PlatformDiscoveryActorResolver,
    slot_reader: PublishedSlotReader,
    option_codec: AppointmentOptionCodec,
) -> None:
    app.include_router(
        create_router(
            candidate_reader=PostgresDiscoveryCandidateReader(session_factory),
            slot_reader=slot_reader,
            option_codec=option_codec,
            actor_resolver=actor_resolver,
        )
    )
