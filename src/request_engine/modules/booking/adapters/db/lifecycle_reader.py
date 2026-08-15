from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.contracts.lifecycle import (
    ReleasedReservationSlot,
    ReservationLifecycleSnapshot,
    ReservationNotificationPlan,
)
from request_engine.modules.booking.domain.lifecycle_policy import reservation_lifecycle_policy
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresReservationLifecycleReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_lifecycle_snapshot(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> ReservationLifecycleSnapshot | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, offering_version_id, subject_party_id, location_id,
                                   lower(during) AS start_at, upper(during) AS end_at,
                                   status, revision, booking_policy_snapshot
                            FROM request_engine.reservations
                            WHERE organization_id = :organization_id AND id = :reservation_id
                            """
                        ),
                        {"organization_id": organization_id, "reservation_id": reservation_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        policy = reservation_lifecycle_policy(
            cast(dict[str, object], row["booking_policy_snapshot"])
        )
        return ReservationLifecycleSnapshot(
            organization_id=organization_id,
            reservation_id=cast(UUID, row["id"]),
            offering_version_id=cast(UUID, row["offering_version_id"]),
            subject_party_id=cast(UUID, row["subject_party_id"]),
            location_id=cast(UUID | None, row["location_id"]),
            start_at=cast(datetime, row["start_at"]),
            end_at=cast(datetime, row["end_at"]),
            status=cast(str, row["status"]),
            revision=cast(int, row["revision"]),
            no_show_after_minutes=policy.attendance.no_show_after_minutes,
            notification_plan=ReservationNotificationPlan(
                confirmation=policy.communications.confirmation,
                reminders_before_minutes=policy.communications.reminders_before_minutes,
                attendance_confirmation_required=policy.attendance.confirmation_required,
                attendance_request_before_minutes=(
                    policy.attendance.attendance_request_before_minutes
                ),
                channel_policy=policy.communications.channel_policy,
            ),
        )

    async def get_released_slot(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        *,
        event_type: str,
    ) -> ReleasedReservationSlot | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            reservation = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT offering_version_id, location_id, lower(during) AS start_at,
                                   upper(during) AS end_at, booking_policy_snapshot
                            FROM request_engine.reservations
                            WHERE organization_id = :organization_id AND id = :reservation_id
                            """
                        ),
                        {"organization_id": organization_id, "reservation_id": reservation_id},
                    )
                )
                .mappings()
                .first()
            )
            if reservation is None:
                return None
            if event_type == "reservation.rescheduled.v1":
                old = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT lower(during) AS start_at, upper(during) AS end_at
                                FROM request_engine.capacity_claims
                                WHERE organization_id = :organization_id
                                  AND reservation_id = :reservation_id
                                  AND status = 'replaced'
                                ORDER BY updated_at DESC, id DESC
                                LIMIT 1
                                """
                            ),
                            {"organization_id": organization_id, "reservation_id": reservation_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if old is None:
                    return None
                start_at = cast(datetime, old["start_at"])
                end_at = cast(datetime, old["end_at"])
            else:
                start_at = cast(datetime, reservation["start_at"])
                end_at = cast(datetime, reservation["end_at"])
            policy = reservation_lifecycle_policy(
                cast(dict[str, object], reservation["booking_policy_snapshot"])
            )
        return ReleasedReservationSlot(
            organization_id=organization_id,
            reservation_id=reservation_id,
            offering_version_id=cast(UUID, reservation["offering_version_id"]),
            location_id=cast(UUID | None, reservation["location_id"]),
            start_at=start_at,
            end_at=end_at,
            recovery_enabled=policy.slot_recovery.enabled,
            minimum_lead_minutes=policy.slot_recovery.minimum_lead_minutes,
        )
