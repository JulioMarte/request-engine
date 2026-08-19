import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from psycopg import Connection
from psycopg.errors import CheckViolation

from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
)
from request_engine.modules.booking.adapters.db.lifecycle_reader import (
    PostgresReservationLifecycleReader,
)
from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    PostgresReservationLifecycleScheduling,
)
from request_engine.modules.booking.adapters.db.slot_offer_capacity import (
    PostgresSlotOfferCapacity,
)
from request_engine.modules.booking.application.commands.check_in_reservation import (
    CheckInReservationCommand,
    check_in_reservation,
)
from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
    evaluate_no_show,
)
from request_engine.modules.booking.application.commands.record_attendance import (
    confirm_attendance,
    decline_attendance,
)
from request_engine.modules.booking.application.errors import (
    ReservationRevisionConflict,
)
from request_engine.modules.booking.contracts.appointments import AttendanceStatus
from request_engine.modules.booking.contracts.attendance import AttendanceOutcomeStatus
from request_engine.modules.communications.adapters.db.reservation_lifecycle_intent import (
    PostgresReservationLifecycleNotificationIntent,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.released_slot_recovery import (
    PostgresReleasedSlotRecovery,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class LifecycleFixture:
    organization_id: UUID
    principal_id: UUID
    subject_id: UUID
    waitlist_subject_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    location_id: UUID
    resource_id: UUID
    reservation_id: UUID
    start_at: datetime
    end_at: datetime


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _party(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, label),
    )


def _fixture(
    conn: PgConnection,
    *,
    policy: dict[str, object],
    start_at: datetime,
    add_waitlist: bool = False,
) -> LifecycleFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"lifecycle-{suffix}", f"Lifecycle {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_id = _party(conn, organization_id, f"Subject {suffix}")
    waitlist_subject_id = _party(conn, organization_id, f"Waitlist {suffix}")
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    full_policy = {"slot_step_minutes": 15, **policy}
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps(full_policy)),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Doctor')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Doctor', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    local_start = start_at.astimezone(ZoneInfo("America/Santo_Domingo"))
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, %s, '00:00', '23:59', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id, local_start.weekday()),
    )
    end_at = start_at + timedelta(minutes=30)
    with conn.transaction():
        reservation_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id,
                location_id, during, booking_policy_snapshot
            ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), %s::jsonb)
            RETURNING id
            """,
            (
                organization_id,
                offering_version_id,
                subject_id,
                location_id,
                start_at,
                end_at,
                json.dumps(full_policy),
            ),
        )
        conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, reservation_id,
                during, quantity
            ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), 1)
            """,
            (
                organization_id,
                resource_id,
                requirement_id,
                reservation_id,
                start_at,
                end_at,
            ),
        )
    if add_waitlist:
        conn.execute(
            """
            INSERT INTO request_engine.waitlist_entries (
                organization_id, offering_id, subject_party_id, location_id
            ) VALUES (%s, %s, %s, %s)
            """,
            (organization_id, offering_id, waitlist_subject_id, location_id),
        )
    return LifecycleFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_id=subject_id,
        waitlist_subject_id=waitlist_subject_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        location_id=location_id,
        resource_id=resource_id,
        reservation_id=reservation_id,
        start_at=start_at,
        end_at=end_at,
    )


def _future_start() -> datetime:
    zone = ZoneInfo("America/Santo_Domingo")
    local_future = datetime.now(zone) + timedelta(days=3)
    # Keep lifecycle fixtures safely inside the declared 00:00-23:59 local
    # availability window regardless of the UTC hour at which CI executes.
    local_start = local_future.replace(hour=12, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_decline_policy_cancels_reservation_and_releases_capacity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={"attendance": {"decline_action": "cancel"}},
        start_at=_future_start(),
    )
    commands = PostgresAttendanceCommands(session_factory)

    state = await decline_attendance(
        commands,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="test:decline",
        idempotency_key=f"decline-{uuid4().hex}",
        expected_revision=1,
        allow_subject_override=True,
    )

    assert state.response_status is AttendanceStatus.DECLINED
    assert state.outcome_status is AttendanceOutcomeStatus.PENDING
    assert state.reservation_revision == 2
    reservation = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert reservation == ("cancelled", 2)
    claim_status = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert claim_status == ("released",)
    event_types = {
        cast(str, row[0])
        for row in admin_conn.execute(
            """
            SELECT event_type
            FROM request_engine.outbox_messages
            WHERE organization_id = %s AND aggregate_id = %s
            """,
            (fixture.organization_id, fixture.reservation_id),
        ).fetchall()
    }
    assert "reservation.attendance_response_recorded.v1" in event_types
    assert "reservation.cancelled.v1" in event_types


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_check_in_fences_no_show_and_keeps_capacity_history(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    start_at = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=1)
    fixture = _fixture(
        admin_conn,
        policy={"attendance": {"no_show_after_minutes": 15}},
        start_at=start_at,
    )
    commands = PostgresAttendanceCommands(session_factory)

    checked_in = await check_in_reservation(
        commands,
        CheckInReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=fixture.reservation_id,
            source_key="test:desk",
            idempotency_key=f"checkin-{uuid4().hex}",
            expected_revision=1,
            allow_subject_override=True,
        ),
    )
    evaluated = await evaluate_no_show(
        commands,
        EvaluateNoShowCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=fixture.reservation_id,
            idempotency_key=f"no-show-{uuid4().hex}",
        ),
    )

    assert checked_in.outcome_status is AttendanceOutcomeStatus.CHECKED_IN
    assert evaluated.outcome_status is AttendanceOutcomeStatus.CHECKED_IN
    claim_status = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert claim_status == ("active",)
    opportunity_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND source_reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert opportunity_count == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_no_show_records_outcome_without_releasing_capacity_or_recovering_slot(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    start_at = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=1)
    fixture = _fixture(
        admin_conn,
        policy={"attendance": {"no_show_after_minutes": 15}},
        start_at=start_at,
    )
    commands = PostgresAttendanceCommands(session_factory)

    state = await evaluate_no_show(
        commands,
        EvaluateNoShowCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=fixture.reservation_id,
            idempotency_key=f"no-show-{uuid4().hex}",
        ),
    )

    assert state.outcome_status is AttendanceOutcomeStatus.NO_SHOW
    assert state.reservation_revision == 2
    claim_status = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert claim_status == ("active",)
    opportunity_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND source_reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert opportunity_count == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_lifecycle_replay_keeps_one_generation_of_notifications_and_no_show_work(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={
            "attendance": {
                "confirmation_required": True,
                "attendance_request_before_minutes": 1440,
                "no_show_after_minutes": 15,
            },
            "communications": {
                "confirmation": True,
                "reminders_before_minutes": [2880, 120],
                "channel_policy": {
                    "channels": ["whatsapp"],
                    "provider_key": "test-provider",
                },
            },
        },
        start_at=_future_start(),
    )
    reader = PostgresReservationLifecycleReader(session_factory)
    scheduling = PostgresReservationLifecycleScheduling(session_factory)
    notifications = PostgresReservationLifecycleNotificationIntent(session_factory)
    snapshot = await reader.get_lifecycle_snapshot(fixture.organization_id, fixture.reservation_id)
    assert snapshot is not None

    await scheduling.reconcile_reservation_schedule(snapshot, source_event_id=uuid4())
    await notifications.reconcile_reservation_notifications(snapshot, source_event_id=uuid4())
    await scheduling.reconcile_reservation_schedule(snapshot, source_event_id=uuid4())
    await notifications.reconcile_reservation_notifications(snapshot, source_event_id=uuid4())

    task_rows = admin_conn.execute(
        """
        SELECT purpose, status
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'Reservation'
          AND source_id = %s
        ORDER BY purpose, id
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert len(task_rows) == 4
    assert all(row[1] == "pending" for row in task_rows)
    assert [row[0] for row in task_rows].count("appointment_reminder") == 2
    scheduled = admin_conn.execute(
        """
        SELECT action_kind, status
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND aggregate_kind = 'Reservation'
          AND aggregate_id = %s
        ORDER BY action_kind, execute_at
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert scheduled == [
        ("reservation.attendance_request", "pending"),
        ("reservation.no_show_check", "pending"),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_cancelled_reservation_recovers_slot_once_and_reuses_phase2b_offer(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={
            "attendance": {"decline_action": "cancel"},
            "slot_recovery": {"enabled": True, "minimum_lead_minutes": 1},
        },
        start_at=_future_start(),
        add_waitlist=True,
    )
    attendance = PostgresAttendanceCommands(session_factory)
    await decline_attendance(
        attendance,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="test:decline-recovery",
        idempotency_key=f"decline-recovery-{uuid4().hex}",
        expected_revision=1,
        allow_subject_override=True,
    )

    reader = PostgresReservationLifecycleReader(session_factory)
    released = await reader.get_released_slot(
        fixture.organization_id,
        fixture.reservation_id,
        event_type="reservation.cancelled.v1",
    )
    assert released is not None
    recovery = PostgresReleasedSlotRecovery(
        session_factory,
        capacity=PostgresSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    first = await recovery.recover_released_slot(
        released,
        source_event_id=uuid4(),
        principal_id=fixture.principal_id,
    )
    second = await recovery.recover_released_slot(
        released,
        source_event_id=uuid4(),
        principal_id=fixture.principal_id,
    )

    assert first is not None
    opportunity, offer = first
    assert offer is not None
    assert second is None
    rows = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND source_reservation_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert rows == [("open",)]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_recovery_respects_lead_time_policy(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    start_at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=30)
    fixture = _fixture(
        admin_conn,
        policy={
            "slot_recovery": {"enabled": True, "minimum_lead_minutes": 120},
        },
        start_at=start_at,
        add_waitlist=True,
    )
    reader = PostgresReservationLifecycleReader(session_factory)
    released = await reader.get_released_slot(
        fixture.organization_id,
        fixture.reservation_id,
        event_type="reservation.cancelled.v1",
    )
    assert released is not None
    recovery = PostgresReleasedSlotRecovery(
        session_factory,
        capacity=PostgresSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    result = await recovery.recover_released_slot(
        released,
        source_event_id=uuid4(),
        principal_id=fixture.principal_id,
    )
    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_confirmation_command_is_idempotent_and_preserves_scheduling_semantics(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={"attendance": {"confirmation_required": True}},
        start_at=_future_start(),
    )
    commands = PostgresAttendanceCommands(session_factory)

    first = await confirm_attendance(
        commands,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="test:confirm",
        idempotency_key="confirm-idempotent",
        expected_revision=1,
        allow_subject_override=True,
    )
    replay = await confirm_attendance(
        commands,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="test:confirm",
        idempotency_key="confirm-idempotent",
        expected_revision=1,
        allow_subject_override=True,
    )

    assert first.response_status is AttendanceStatus.CONFIRMED
    assert replay == first
    assert first.reservation_revision == 2
    scheduled_rows = admin_conn.execute(
        """
        SELECT action_kind
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND aggregate_kind = 'Reservation'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert scheduled_rows == []


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reservation_lifecycle_reader_snapshots_policy_and_timezone(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={
            "attendance": {"confirmation_required": True},
            "communications": {"confirmation": True},
        },
        start_at=_future_start(),
    )
    reader = PostgresReservationLifecycleReader(session_factory)
    snapshot = await reader.get_lifecycle_snapshot(fixture.organization_id, fixture.reservation_id)

    assert snapshot is not None
    assert snapshot.start_at == fixture.start_at
    assert snapshot.end_at == fixture.end_at
    assert snapshot.location_timezone == "America/Santo_Domingo"
    assert snapshot.booking_policy["attendance"] == {"confirmation_required": True}
    assert snapshot.booking_policy["communications"] == {"confirmation": True}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_invalid_attendance_row_with_conflicting_terminal_timestamps_is_rejected(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={},
        start_at=_future_start(),
    )
    with pytest.raises(CheckViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservation_attendance (
                organization_id, reservation_id, status, checked_in_at, no_show_at
            ) VALUES (%s, %s, 'no_show', clock_timestamp(), clock_timestamp())
            """,
            (fixture.organization_id, fixture.reservation_id),
        )
