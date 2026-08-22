from datetime import UTC
from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.adapters.db import contextual_terms_supersession_codec as codec
from request_engine.modules.booking.adapters.db import contextual_terms_supersession_locking as locking
from request_engine.modules.booking.adapters.db import contextual_terms_supersession_store as store
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
)
from request_engine.modules.booking.application.operational_errors import ContextualConfigurationConflict
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    require_operational_authority,
)


class PostgresContextualTermsSupersessionCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def supersede_booking_context_terms(
        self,
        command: SupersedeBookingContextTermsCommand,
    ) -> BookingContextTermsState:
        cutover = command.effective_from.astimezone(UTC)
        fingerprint = command_fingerprint(
            "booking.supersede_booking_context_terms",
            codec.command_payload(command, cutover=cutover),
        )
        try:
            async with tenant_transaction(self._session_factory, command.organization_id) as session:
                idem_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="booking.supersede_booking_context_terms",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return codec.from_json(cast(dict[str, object], replay["terms"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                assignment_id, offering_version_id = await locking.lock_identity(
                    session,
                    organization_id=command.organization_id,
                    terms_id=command.current_context_terms_id,
                )
                starts_at, ends_at, revision = await locking.lock_current_range(
                    session,
                    organization_id=command.organization_id,
                    terms_id=command.current_context_terms_id,
                )
                if revision != command.expected_current_revision:
                    raise ContextualConfigurationConflict("BookingContextTerms revision is stale")
                if cutover <= starts_at or (ends_at is not None and cutover >= ends_at):
                    raise ContextualConfigurationConflict(
                        "cutover must be inside current effective range"
                    )
                new_id, new_revision = await store.cutover_and_insert(
                    session,
                    organization_id=command.organization_id,
                    current_terms_id=command.current_context_terms_id,
                    assignment_id=assignment_id,
                    offering_version_id=offering_version_id,
                    cutover=cutover,
                    previous_end=ends_at,
                    amount=command.amount,
                    currency=command.currency,
                    duration=command.planned_duration_minutes,
                    bookable=command.bookable,
                )
                state = BookingContextTermsState(
                    context_terms_id=new_id,
                    resource_location_assignment_id=assignment_id,
                    offering_version_id=offering_version_id,
                    effective_from=cutover,
                    effective_until=ends_at,
                    amount=command.amount,
                    currency=command.currency,
                    planned_duration_minutes=command.planned_duration_minutes,
                    bookable=command.bookable,
                    revision=new_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.supersede_booking_context_terms",
                    aggregate_kind="BookingContextTerms",
                    aggregate_id=new_id,
                    idempotency_id=idem_id,
                    details={
                        "authority": authority.audit_details(),
                        "superseded_context_terms_id": str(command.current_context_terms_id),
                        "cutover": cutover.isoformat(),
                    },
                )
                await complete_idempotency(session, idem_id, {"terms": codec.to_json(state)})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise ContextualConfigurationConflict(
                    "BookingContextTerms overlap effective configuration"
                ) from None
            raise
