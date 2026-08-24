from uuid import UUID

from request_engine.modules.booking.api.models import BookAppointmentBody
from request_engine.modules.booking.application.authority import SUBJECT_OVERRIDE_PERMISSION
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    BookAppointmentHandler,
    book_appointment,
)
from request_engine.modules.booking.contracts.appointment_options import (
    AppointmentOptionCodec,
    DecodedAppointmentOption,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.discovery import DiscoveryHandoffReader
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.discovery_handoff_context import (
    reset_discovery_handoff_id,
    set_discovery_handoff_id,
)


async def book_selected_option(
    *,
    body: BookAppointmentBody,
    actor: ActorContext,
    idempotency_key: str,
    option_codec: AppointmentOptionCodec,
    handoff_reader: DiscoveryHandoffReader,
    handler: BookAppointmentHandler,
) -> Reservation:
    option, handoff_id = await _resolve_option(
        body.option_id,
        actor.organization_id,
        option_codec,
        handoff_reader,
    )
    token = set_discovery_handoff_id(handoff_id) if handoff_id is not None else None
    try:
        return await book_appointment(handler, _command(body, actor, idempotency_key, option))
    finally:
        if token is not None:
            reset_discovery_handoff_id(token)


async def _resolve_option(
    token: str,
    organization_id: UUID,
    option_codec: AppointmentOptionCodec,
    handoff_reader: DiscoveryHandoffReader,
) -> tuple[DecodedAppointmentOption, UUID | None]:
    if token.startswith("discoopt_v1."):
        handoff = await handoff_reader.read_handoff(organization_id, token)
        return handoff.option, handoff.handoff_id
    return option_codec.decode(organization_id, token), None


def _command(
    body: BookAppointmentBody,
    actor: ActorContext,
    idempotency_key: str,
    option: DecodedAppointmentOption,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=actor.organization_id,
        principal_id=actor.principal_id,
        offering_version_id=option.offering_version_id,
        subject_party_id=body.subject_party_id,
        start_at=option.start_at,
        resources=option.resources,
        location_id=option.location_id,
        origin_request_id=body.origin_request_id,
        idempotency_key=idempotency_key,
        allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
        expected_planned_duration_minutes=option.planned_duration_minutes,
        expected_amount=option.amount,
        expected_currency=option.currency,
        expected_location_operational_revision=option.location_operational_revision,
        expected_configuration_fingerprint=option.configuration_fingerprint,
    )
