from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import contextual_terms_supersession_codec as codec
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.idempotency.postgres import complete_idempotency
from request_engine.platform.security.operational_authority import OperationalAuthorityGrant


async def finalize(
    session: AsyncSession,
    *,
    command: SupersedeBookingContextTermsCommand,
    authority: OperationalAuthorityGrant,
    idempotency_id: UUID,
    state: BookingContextTermsState,
    cutover: datetime,
) -> None:
    await append_audit(
        session,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        command_name="booking.supersede_booking_context_terms",
        aggregate_kind="BookingContextTerms",
        aggregate_id=state.context_terms_id,
        idempotency_id=idempotency_id,
        details={
            "authority": authority.audit_details(),
            "superseded_context_terms_id": str(command.current_context_terms_id),
            "cutover": cutover.isoformat(),
        },
    )
    await complete_idempotency(
        session,
        idempotency_id,
        {"terms": codec.to_json(state)},
    )
