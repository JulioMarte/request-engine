from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.reservation_commands import (
    ensure_reservation_revision,
    lock_resource_ids,
)
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.attendance_errors import (
    AttendanceOutcomeConflict,
    AttendanceReservationNotActive,
    NoShowEvaluationTooEarly,
)
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.check_in_reservation import (
    CheckInReservationCommand,
)
from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
)
from request_engine.modules.booking.application.commands.record_attendance import (
    RecordAttendanceResponseCommand,
)
from request_engine.modules.booking.application.errors import ReservationNotFound
from request_engine.modules.booking.contracts.appointments import AttendanceStatus
from request_engine.modules.booking.contracts.attendance import (
    AttendanceOutcomeStatus,
    ReservationAttendanceState,
)
from request_engine.modules.booking.domain.lifecycle_policy import reservation_lifecycle_policy
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import lock_action_claim
from request_engine.platform.worker.runtime import LeaseLostWorkError


class PostgresAttendanceCommands:
    """Booking-owned attendance response, check-in and no-show mutations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def record_attendance_response(
        self,
        command: RecordAttendanceResponseCommand,
    ) -> ReservationAttendanceState:
        capability = "booking.record_attendance_response"
        fingerprint = command_fingerprint(
            capability,
            {
                "reservation_id": command.reservation_id,
                "response": command.response,
                "source_key": command.source_key,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=capability,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["attendance"]))

            reservation = await _lock_reservation(
                session, command.organization_id, command.reservation_id
            )
            subject_party_id = cast(UUID, reservation["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            ensure_reservation_revision(
                reservation, command.reservation_id, command.expected_revision
            )
            if cast(str, reservation["status"]) != "confirmed":
                raise AttendanceReservationNotActive(
                    command.reservation_id, cast(str, reservation["status"])
                )
            response_row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO request_engine.attendance_responses (
                                organization_id, reservation_id, response,
                                actor_principal_id, source_key
                            ) VALUES (
                                :organization_id, :reservation_id, :response,
                                :principal_id, :source_key
                            )
                            RETURNING id, responded_at
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "reservation_id": command.reservation_id,
                            "response": command.response,
                            "principal_id": command.principal_id,
                            "source_key": command.source_key,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await _ensure_attendance_projection(
                session, command.organization_id, command.reservation_id
            )

            policy = reservation_lifecycle_policy(
                cast(dict[str, object], reservation["booking_policy_snapshot"])
            )
            cancelled = (
                command.response == "declined" and policy.attendance.decline_action == "cancel"
            )
            if cancelled:
                resource_ids = await _active_resource_ids(
                    session, command.organization_id, command.reservation_id
                )
                if resource_ids:
                    await lock_resource_ids(session, command.organization_id, resource_ids)
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.capacity_claims
                            SET status = 'released', released_at = clock_timestamp(),
                                updated_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND reservation_id = :reservation_id
                              AND status = 'active'
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "reservation_id": command.reservation_id,
                        },
                    )
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservations
                        SET status = 'cancelled', cancelled_at = clock_timestamp(),
                            revision = revision + 1, updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )
                await _cancel_booking_lifecycle_actions(
                    session, command.organization_id, command.reservation_id
                )
            else:
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservations
                        SET revision = revision + 1, updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=capability,
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "response": command.response,
                    "source_key": command.source_key,
                    "expected_revision": command.expected_revision,
                    "subject_authority": authority.audit_details(),
                    "policy_cancelled_reservation": cancelled,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.attendance_response_recorded.v1",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload={
                    "reservation_id": str(command.reservation_id),
                    "response_id": str(cast(UUID, response_row["id"])),
                    "response": command.response,
                    "source_key": command.source_key,
                    "policy_cancelled_reservation": cancelled,
                },
            )
            if cancelled:
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="reservation.cancelled.v1",
                    aggregate_kind="Reservation",
                    aggregate_id=command.reservation_id,
                    payload={
                        "reservation_id": str(command.reservation_id),
                        "reason": "attendance_declined",
                        "source": "attendance_policy",
                    },
                )

            state = await _read_state(session, command.organization_id, command.reservation_id)
            await complete_idempotency(
                session,
                idempotency_id,
                {"attendance": _state_to_json(state)},
            )
            return state

    async def check_in_reservation(
        self,
        command: CheckInReservationCommand,
    ) -> ReservationAttendanceState:
        fingerprint = command_fingerprint(
            "booking.check_in_reservation",
            {
                "reservation_id": command.reservation_id,
                "source_key": command.source_key,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="appointments.check_in",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["attendance"]))

            reservation = await _lock_reservation(
                session, command.organization_id, command.reservation_id
            )
            if cast(str, reservation["status"]) != "confirmed":
                raise AttendanceReservationNotActive(
                    command.reservation_id, cast(str, reservation["status"])
                )
            ensure_reservation_revision(
                reservation, command.reservation_id, command.expected_revision
            )
            subject_party_id = cast(UUID, reservation["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            await _ensure_attendance_projection(
                session, command.organization_id, command.reservation_id
            )
            attendance = await _lock_attendance(
                session, command.organization_id, command.reservation_id
            )
            current = AttendanceOutcomeStatus(cast(str, attendance["status"]))
            if current is AttendanceOutcomeStatus.NO_SHOW:
                raise AttendanceOutcomeConflict(command.reservation_id, current.value)
            if current is AttendanceOutcomeStatus.PENDING:
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservation_attendance
                        SET status = 'checked_in', checked_in_at = clock_timestamp(),
                            source_key = :source_key, revision = revision + 1,
                            updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND reservation_id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                        "source_key": command.source_key,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservations
                        SET revision = revision + 1, updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id AND id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )
                await _cancel_booking_lifecycle_actions(
                    session, command.organization_id, command.reservation_id
                )
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="reservation.checked_in.v1",
                    aggregate_kind="Reservation",
                    aggregate_id=command.reservation_id,
                    payload={
                        "reservation_id": str(command.reservation_id),
                        "source_key": command.source_key,
                    },
                )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.check_in_reservation",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "source_key": command.source_key,
                    "expected_revision": command.expected_revision,
                    "subject_authority": authority.audit_details(),
                    "already_checked_in": current is AttendanceOutcomeStatus.CHECKED_IN,
                },
            )
            state = await _read_state(session, command.organization_id, command.reservation_id)
            await complete_idempotency(
                session, idempotency_id, {"attendance": _state_to_json(state)}
            )
            return state

    async def evaluate_no_show(
        self,
        command: EvaluateNoShowCommand,
    ) -> ReservationAttendanceState:
        fingerprint = command_fingerprint(
            "booking.evaluate_no_show",
            {"reservation_id": command.reservation_id},
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            if command.scheduled_action_id is not None:
                claim_token = command.scheduled_action_claim_token
                assert claim_token is not None
                if not await lock_action_claim(
                    session,
                    action_id=command.scheduled_action_id,
                    claim_token=claim_token,
                ):
                    raise LeaseLostWorkError("no_show_authoritative_fence_lost")

            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="appointments.evaluate_no_show",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["attendance"]))

            reservation = await _lock_reservation(
                session, command.organization_id, command.reservation_id
            )
            await _ensure_attendance_projection(
                session, command.organization_id, command.reservation_id
            )
            if cast(str, reservation["status"]) != "confirmed":
                state = await _read_state(session, command.organization_id, command.reservation_id)
                await complete_idempotency(
                    session, idempotency_id, {"attendance": _state_to_json(state)}
                )
                return state

            policy = reservation_lifecycle_policy(
                cast(dict[str, object], reservation["booking_policy_snapshot"])
            )
            no_show_after = policy.attendance.no_show_after_minutes
            if no_show_after is None:
                state = await _read_state(session, command.organization_id, command.reservation_id)
                await complete_idempotency(
                    session, idempotency_id, {"attendance": _state_to_json(state)}
                )
                return state

            db_now = cast(
                datetime,
                (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
            )
            cutoff = cast(datetime, reservation["start_at"]) + timedelta(minutes=no_show_after)
            if db_now < cutoff:
                raise NoShowEvaluationTooEarly(command.reservation_id)

            attendance = await _lock_attendance(
                session, command.organization_id, command.reservation_id
            )
            current = AttendanceOutcomeStatus(cast(str, attendance["status"]))
            if current is AttendanceOutcomeStatus.PENDING:
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservation_attendance
                        SET status = 'no_show', no_show_at = clock_timestamp(),
                            source_key = 'scheduled:no_show', revision = revision + 1,
                            updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id
                          AND reservation_id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE request_engine.reservations
                        SET revision = revision + 1, updated_at = clock_timestamp()
                        WHERE organization_id = :organization_id AND id = :reservation_id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "reservation_id": command.reservation_id,
                    },
                )
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="reservation.no_show_recorded.v1",
                    aggregate_kind="Reservation",
                    aggregate_id=command.reservation_id,
                    payload={
                        "reservation_id": str(command.reservation_id),
                        "cutoff_at": cutoff.isoformat(),
                    },
                )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.evaluate_no_show",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "cutoff_at": cutoff.isoformat(),
                    "outcome_before": current.value,
                },
            )
            state = await _read_state(session, command.organization_id, command.reservation_id)
            await complete_idempotency(
                session, idempotency_id, {"attendance": _state_to_json(state)}
            )
            return state


async def _lock_reservation(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, status, subject_party_id, revision,
                           booking_policy_snapshot,
                           lower(during) AS start_at,
                           upper(during) AS end_at,
                           offering_version_id, location_id
                    FROM request_engine.reservations
                    WHERE organization_id = :organization_id AND id = :reservation_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReservationNotFound(reservation_id)
    return row


async def _ensure_attendance_projection(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.reservation_attendance (organization_id, reservation_id)
            VALUES (:organization_id, :reservation_id)
            ON CONFLICT (organization_id, reservation_id) DO NOTHING
            """
        ),
        {"organization_id": organization_id, "reservation_id": reservation_id},
    )


async def _lock_attendance(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT * FROM request_engine.reservation_attendance
                    WHERE organization_id = :organization_id AND reservation_id = :reservation_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .one()
    )


async def _active_resource_ids(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> tuple[UUID, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT resource_id
                FROM request_engine.capacity_claims
                WHERE organization_id = :organization_id
                  AND reservation_id = :reservation_id
                  AND status = 'active'
                ORDER BY resource_id
                """
            ),
            {"organization_id": organization_id, "reservation_id": reservation_id},
        )
    ).all()
    return tuple(cast(UUID, row[0]) for row in rows)


async def _cancel_booking_lifecycle_actions(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.scheduled_actions
            SET status = 'cancelled', updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND owner_module = 'booking'
              AND subject_kind = 'Reservation'
              AND subject_id = :reservation_id
              AND status = 'pending'
            """
        ),
        {"organization_id": organization_id, "reservation_id": reservation_id},
    )


async def _read_state(
    session: AsyncSession, organization_id: UUID, reservation_id: UUID
) -> ReservationAttendanceState:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT r.id AS reservation_id,
                           r.revision AS reservation_revision,
                           ar.id AS response_id,
                           ar.response,
                           ar.responded_at,
                           ra.status AS outcome_status,
                           ra.checked_in_at,
                           ra.no_show_at
                    FROM request_engine.reservations r
                    LEFT JOIN LATERAL (
                        SELECT id, response, responded_at
                        FROM request_engine.attendance_responses
                        WHERE organization_id = r.organization_id
                          AND reservation_id = r.id
                        ORDER BY responded_at DESC, id DESC
                        LIMIT 1
                    ) ar ON true
                    LEFT JOIN request_engine.reservation_attendance ra
                      ON ra.organization_id = r.organization_id
                     AND ra.reservation_id = r.id
                    WHERE r.organization_id = :organization_id AND r.id = :reservation_id
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .one()
    )
    raw_response = cast(str | None, row["response"])
    return ReservationAttendanceState(
        reservation_id=cast(UUID, row["reservation_id"]),
        reservation_revision=cast(int, row["reservation_revision"]),
        response_status=(
            AttendanceStatus(raw_response) if raw_response is not None else AttendanceStatus.PENDING
        ),
        outcome_status=AttendanceOutcomeStatus(
            cast(str | None, row["outcome_status"]) or AttendanceOutcomeStatus.PENDING.value
        ),
        response_id=cast(UUID | None, row["response_id"]),
        responded_at=cast(datetime | None, row["responded_at"]),
        checked_in_at=cast(datetime | None, row["checked_in_at"]),
        no_show_at=cast(datetime | None, row["no_show_at"]),
    )


def _state_to_json(state: ReservationAttendanceState) -> dict[str, object]:
    return {
        "reservation_id": str(state.reservation_id),
        "reservation_revision": state.reservation_revision,
        "response_status": state.response_status.value,
        "outcome_status": state.outcome_status.value,
        "response_id": str(state.response_id) if state.response_id else None,
        "responded_at": state.responded_at.isoformat() if state.responded_at else None,
        "checked_in_at": state.checked_in_at.isoformat() if state.checked_in_at else None,
        "no_show_at": state.no_show_at.isoformat() if state.no_show_at else None,
    }


def _state_from_json(data: dict[str, object]) -> ReservationAttendanceState:
    def dt(key: str) -> datetime | None:
        raw = cast(str | None, data.get(key))
        return datetime.fromisoformat(raw) if raw is not None else None

    raw_response_id = cast(str | None, data.get("response_id"))
    return ReservationAttendanceState(
        reservation_id=UUID(cast(str, data["reservation_id"])),
        reservation_revision=cast(int, data["reservation_revision"]),
        response_status=AttendanceStatus(cast(str, data["response_status"])),
        outcome_status=AttendanceOutcomeStatus(cast(str, data["outcome_status"])),
        response_id=UUID(raw_response_id) if raw_response_id else None,
        responded_at=dt("responded_at"),
        checked_in_at=dt("checked_in_at"),
        no_show_at=dt("no_show_at"),
    )
