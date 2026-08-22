from datetime import UTC
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
        self, command: SupersedeBookingContextTermsCommand
    ) -> BookingContextTermsState:
        cutover = command.effective_from.astimezone(UTC)
        fingerprint = command_fingerprint(
            "booking.supersede_booking_context_terms",
            {
                "authority_party_id": command.authority_party_id,
                "current_context_terms_id": command.current_context_terms_id,
                "expected_current_revision": command.expected_current_revision,
                "effective_from": cutover,
                "amount": str(command.amount) if command.amount is not None else None,
                "currency": command.currency,
                "planned_duration_minutes": command.planned_duration_minutes,
                "bookable": command.bookable,
            },
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
                    return _state_from_json(cast(dict[str, object], replay["terms"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                identity = (
                    (
                        await session.execute(
                            text("""
                                SELECT b.resource_location_assignment_id, b.offering_version_id,
                                       a.resource_id
                                FROM request_engine.booking_context_terms b
                                JOIN request_engine.resource_location_assignments a
                                  ON a.organization_id = b.organization_id
                                 AND a.id = b.resource_location_assignment_id
                                WHERE b.organization_id = :organization_id
                                  AND b.id = :terms_id
                            """),
                            {"organization_id": command.organization_id, "terms_id": command.current_context_terms_id},
                        )
                    ).mappings().first()
                )
                if identity is None:
                    raise ContextualConfigurationConflict("BookingContextTerms is missing or foreign")
                assignment_id = cast(UUID, identity["resource_location_assignment_id"])
                resource_id = cast(UUID, identity["resource_id"])
                await session.execute(
                    text("SELECT id FROM request_engine.resources WHERE organization_id=:o AND id=:r FOR UPDATE"),
                    {"o": command.organization_id, "r": resource_id},
                )
                assignment = (
                    await session.execute(
                        text("SELECT status FROM request_engine.resource_location_assignments WHERE organization_id=:o AND id=:a FOR UPDATE"),
                        {"o": command.organization_id, "a": assignment_id},
                    )
                ).first()
                if assignment is None or assignment[0] != "active":
                    raise ContextualConfigurationConflict("ResourceLocationAssignment is not configurable")
                current = (
                    (
                        await session.execute(
                            text("""
                                SELECT lower(effective_during) AS starts_at,
                                       upper(effective_during) AS ends_at, revision
                                FROM request_engine.booking_context_terms
                                WHERE organization_id=:o AND id=:t
                                FOR UPDATE
                            """),
                            {"o": command.organization_id, "t": command.current_context_terms_id},
                        )
                    ).mappings().one()
                )
                revision = cast(int, current["revision"])
                if revision != command.expected_current_revision:
                    raise ContextualConfigurationConflict("BookingContextTerms revision is stale")
                if cutover <= current["starts_at"] or (
                    current["ends_at"] is not None and cutover >= current["ends_at"]
                ):
                    raise ContextualConfigurationConflict("cutover must be inside current effective range")
                await session.execute(
                    text("UPDATE request_engine.booking_context_terms SET effective_during=tstzrange(lower(effective_during), :cutover, '[)') WHERE organization_id=:o AND id=:t"),
                    {"cutover": cutover, "o": command.organization_id, "t": command.current_context_terms_id},
                )
                row = (
                    (
                        await session.execute(
                            text("""
                                INSERT INTO request_engine.booking_context_terms (
                                    organization_id, resource_location_assignment_id, offering_version_id,
                                    effective_during, amount, currency, planned_duration_minutes, bookable
                                ) VALUES (:o, :a, :v, tstzrange(:cutover, :ends_at, '[)'), :amount, :currency, :duration, :bookable)
                                RETURNING id, revision
                            """),
                            {"o": command.organization_id, "a": assignment_id, "v": identity["offering_version_id"], "cutover": cutover, "ends_at": current["ends_at"], "amount": command.amount, "currency": command.currency, "duration": command.planned_duration_minutes, "bookable": command.bookable},
                        )
                    ).mappings().one()
                )
                state = BookingContextTermsState(cast(UUID, row["id"]), assignment_id, cast(UUID, identity["offering_version_id"]), cutover, current["ends_at"], command.amount, command.currency, command.planned_duration_minutes, command.bookable, cast(int, row["revision"]))
                await append_audit(session, organization_id=command.organization_id, principal_id=command.principal_id, command_name="booking.supersede_booking_context_terms", aggregate_kind="BookingContextTerms", aggregate_id=state.context_terms_id, idempotency_id=idem_id, details={"authority": authority.audit_details(), "superseded_context_terms_id": str(command.current_context_terms_id), "cutover": cutover.isoformat()})
                await complete_idempotency(session, idem_id, {"terms": _state_to_json(state)})
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise ContextualConfigurationConflict("BookingContextTerms overlap effective configuration") from None
            raise


def _state_to_json(state: BookingContextTermsState) -> dict[str, object]:
    return {"context_terms_id": str(state.context_terms_id), "resource_location_assignment_id": str(state.resource_location_assignment_id), "offering_version_id": str(state.offering_version_id), "effective_from": state.effective_from.isoformat(), "effective_until": state.effective_until.isoformat() if state.effective_until else None, "amount": str(state.amount) if state.amount is not None else None, "currency": state.currency, "planned_duration_minutes": state.planned_duration_minutes, "bookable": state.bookable, "revision": state.revision}


def _state_from_json(value: dict[str, object]) -> BookingContextTermsState:
    from datetime import datetime
    from decimal import Decimal
    end = cast(str | None, value.get("effective_until")); amount = cast(str | None, value.get("amount"))
    return BookingContextTermsState(UUID(cast(str, value["context_terms_id"])), UUID(cast(str, value["resource_location_assignment_id"])), UUID(cast(str, value["offering_version_id"])), datetime.fromisoformat(cast(str, value["effective_from"])), datetime.fromisoformat(end) if end else None, Decimal(amount) if amount else None, cast(str | None, value.get("currency")), cast(int | None, value.get("planned_duration_minutes")), cast(bool, value["bookable"]), cast(int, value["revision"]))
