"""Cross-Organization recovery commitment authority.

Booking owns both boundaries of the F5 external replacement saga: the new
commitment is booked in the provider Organization through the discovery
handoff fence, and the degraded source commitment is cancelled only through
this same reviewed surface. The provider-side referral principal is a
tenant-scoped service principal provisioned lazily so no requester identity
ever reaches provider tables.
"""

from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    PostgresContextualReservationCommands,
)
from request_engine.modules.booking.adapters.discovery_handoff_reader import (
    PostgresDiscoveryHandoffReader,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryDisposalRequest,
    RecoveryExternalBookingRequest,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.security.discovery_handoff_context import (
    reset_discovery_handoff_id,
    set_discovery_handoff_id,
)
from request_engine.platform.security.execution_context import (
    anonymous_execution_identity,
    system_execution_identity,
)

REFERRAL_PRINCIPAL_SUBJECT = "recovery_referral_acceptance"

_ENSURE_REFERRAL_PRINCIPAL = text(
    """
    INSERT INTO request_engine.principals (
        organization_id, principal_kind, external_subject
    ) VALUES (
        :organization_id, 'service', :external_subject
    )
    ON CONFLICT (organization_id, principal_kind, external_subject)
    DO UPDATE SET updated_at = clock_timestamp()
    RETURNING id
    """
)


class PostgresRecoveryExternalBooking:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._commands = PostgresContextualReservationCommands(session_factory)
        self._handoffs = PostgresDiscoveryHandoffReader(session_factory)

    async def book_discovered_option(self, request: RecoveryExternalBookingRequest) -> Reservation:
        principal_id = await self._ensure_referral_principal(request.organization_id)
        async with system_execution_identity(
            organization_id=request.organization_id,
            principal_id=principal_id,
            authentication_method="recovery_referral",
        ):
            handoff = await self._handoffs.read_handoff(request.organization_id, request.option_id)
            token = set_discovery_handoff_id(handoff.handoff_id)
            try:
                return await book_appointment(
                    self._commands,
                    BookAppointmentCommand(
                        organization_id=request.organization_id,
                        principal_id=principal_id,
                        offering_version_id=handoff.option.offering_version_id,
                        subject_party_id=request.subject_party_id,
                        start_at=handoff.option.start_at,
                        resources=handoff.option.resources,
                        location_id=handoff.option.location_id,
                        idempotency_key=f"recovery:{request.action_id}:external:v1",
                        allow_subject_override=True,
                        expected_planned_duration_minutes=(handoff.option.planned_duration_minutes),
                        expected_amount=handoff.option.amount,
                        expected_currency=handoff.option.currency,
                        expected_location_operational_revision=(
                            handoff.option.location_operational_revision
                        ),
                        expected_configuration_fingerprint=(
                            handoff.option.configuration_fingerprint
                        ),
                    ),
                )
            finally:
                reset_discovery_handoff_id(token)

    async def cancel_for_recovery(self, request: RecoveryDisposalRequest) -> Reservation:
        return await cancel_reservation(
            self._commands,
            CancelReservationCommand(
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                reservation_id=request.reservation_id,
                idempotency_key=f"recovery:{request.action_id}:dispose:v1",
                expected_revision=request.expected_revision,
                reason=request.reason or "replaced through cross-organization recovery",
                allow_subject_override=True,
            ),
        )

    async def _ensure_referral_principal(self, organization_id: UUID) -> UUID:
        async with (
            anonymous_execution_identity(),
            tenant_transaction(self._session_factory, organization_id) as session,
        ):
            row = (
                await session.execute(
                    _ENSURE_REFERRAL_PRINCIPAL,
                    {
                        "organization_id": organization_id,
                        "external_subject": REFERRAL_PRINCIPAL_SUBJECT,
                    },
                )
            ).scalar_one()
        return UUID(str(row))
