from request_engine.modules.booking.adapters.appointment_options import SignedAppointmentOptionCodec
from request_engine.modules.booking.adapters.discovery_slot_reader import PostgresPublishedSlotReader
from request_engine.modules.booking.contracts.appointment_options import AppointmentOptionCodec
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.platform.db.session import SessionFactory


def build_published_slot_reader(session_factory: SessionFactory) -> PublishedSlotReader:
    return PostgresPublishedSlotReader(session_factory)


def build_appointment_option_codec(signing_key: bytes) -> AppointmentOptionCodec:
    return SignedAppointmentOptionCodec(signing_key)
