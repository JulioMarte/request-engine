from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.booking.adapters.db.arrival_estimate_codec import (
    estimate_from_json,
    estimate_to_json,
)
from request_engine.modules.booking.adapters.db.arrival_estimate_store import (
    advance_reservation_revision,
    estimate_audit_details,
    estimate_outbox_payload,
    lock_reservation,
    supersede_and_insert,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    ensure_reservation_revision,
)
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateCommand,
)
from request_engine.modules.booking.application.errors import ReservationNotConfirmed
from request_engine.modules.booking.contracts.arrival_estimates import (
    ArrivalEstimateSource,
    ReservationArrivalEstimate,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox

_CAPABILITY = "booking.record_arrival_estimate"


class PostgresArrivalEstimateCommands:
    """Booking-owned reservation arrival estimate recording."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record_arrival_estimate(
        self,
        command: RecordArrivalEstimateCommand,
    ) -> ReservationArrivalEstimate:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "reservation_id": command.reservation_id,
                "estimated_arrival_at": command.estimated_arrival_at.isoformat(),
                "source_kind": command.source_kind.value,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="appointments.record_arrival_estimate",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return estimate_from_json(cast(dict[str, object], replay["estimate"]))

            reservation = await lock_reservation(
                session, command.organization_id, command.reservation_id
            )
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=cast(UUID, reservation["subject_party_id"]),
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            ensure_reservation_revision(
                reservation, command.reservation_id, command.expected_revision
            )
            if cast(str, reservation["status"]) != "confirmed":
                raise ReservationNotConfirmed(
                    command.reservation_id, cast(str, reservation["status"])
                )

            estimate_row = await supersede_and_insert(session, command)
            state = ReservationArrivalEstimate(
                reservation_id=command.reservation_id,
                reservation_revision=await advance_reservation_revision(
                    session, command.organization_id, command.reservation_id
                ),
                estimate_id=cast(UUID, estimate_row["id"]),
                estimated_arrival_at=command.estimated_arrival_at,
                source_kind=ArrivalEstimateSource(command.source_kind.value),
                asserted_at=cast(datetime, estimate_row["asserted_at"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    **estimate_audit_details(command, state.estimate_id),
                    "subject_authority": authority.audit_details(),
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.arrival_estimate_recorded.v1",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload=estimate_outbox_payload(command, state.estimate_id),
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"estimate": estimate_to_json(state)},
            )
            return state
