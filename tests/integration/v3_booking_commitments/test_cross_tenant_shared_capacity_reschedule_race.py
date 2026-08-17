import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import reservation_commands as reservation_db
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    reschedule_reservation,
)
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
SharedRootLocker = Callable[[AsyncSession, UUID, tuple[UUID, ...]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TenantFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    offering_version_id: UUID
    location_id: UUID
    requirement_id: UUID
    capability_id: UUID
    resource_ids: tuple[UUID, UUID]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _tenant(conn: PgConnection, label: str) -> TenantFixture:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (suffix, suffix),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s) RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s) RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo') RETURNING id
        """,
        (organization_id, f"main-{suffix}", f"Main {suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"consult-{suffix}", f"Consult {suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb) RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"doctor-{suffix}", f"Doctor {suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )

    resource_ids: list[UUID] = []
    for ordinal in (1, 2):
        resource_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.resources (
                organization_id, location_id, resource_key, display_name,
                capacity_model, capacity_units
            ) VALUES (%s, %s, %s, %s, 'exclusive', 1) RETURNING id
            """,
            (
                organization_id,
                location_id,
                f"doctor-{ordinal}-{suffix}",
                f"Doctor {ordinal} {suffix}",
            ),
        )
        resource_ids.append(resource_id)
        conn.execute(
            """
            INSERT INTO request_engine.resource_capability_assignments (
                organization_id, resource_id, capability_id
            ) VALUES (%s, %s, %s)
            """,
            (organization_id, resource_id, capability_id),
        )
        conn.execute(
            """
            INSERT INTO request_engine.availability_schedules (
                organization_id, resource_id, weekday, local_start, local_end, timezone
            ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
            """,
            (organization_id, resource_id),
        )

    return TenantFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        offering_version_id=offering_version_id,
        location_id=location_id,
        requirement_id=requirement_id,
        capability_id=capability_id,
        resource_ids=cast(tuple[UUID, UUID], tuple(resource_ids)),
    )


def _shared_root(conn: PgConnection, label: str) -> UUID:
    identity_id = _uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", f"verified {label}"),
    )
    return _uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", f"serialize {label}"),
    )


def _bind(
    conn: PgConnection,
    fixture: TenantFixture,
    resource_id: UUID,
    root_id: UUID,
) -> None:
    conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            resource_id,
            root_id,
            "test.control-plane",
            "cross-tenant reschedule race proof",
        ),
    )


def _book_command(
    fixture: TenantFixture,
    resource_id: UUID,
    start_at: datetime,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        resources=(ResourceChoice(fixture.requirement_id, resource_id),),
        idempotency_key=f"book-{uuid4().hex}",
        allow_subject_override=True,
    )


def _reschedule_command(
    fixture: TenantFixture,
    *,
    reservation_id: UUID,
    expected_revision: int,
    resource_id: UUID,
    start_at: datetime,
) -> RescheduleReservationCommand:
    return RescheduleReservationCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=reservation_id,
        expected_revision=expected_revision,
        location_id=fixture.location_id,
        start_at=start_at,
        resources=(ResourceChoice(fixture.requirement_id, resource_id),),
        idempotency_key=f"reschedule-{uuid4().hex}",
        allow_subject_override=True,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_simultaneous_cross_tenant_reschedules_acquire_shared_roots_canonically(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a = _tenant(admin_conn, "reschedule-a")
    tenant_b = _tenant(admin_conn, "reschedule-b")
    root_one = _shared_root(admin_conn, "root-one")
    root_two = _shared_root(admin_conn, "root-two")

    _bind(admin_conn, tenant_a, tenant_a.resource_ids[0], root_one)
    _bind(admin_conn, tenant_a, tenant_a.resource_ids[1], root_two)
    _bind(admin_conn, tenant_b, tenant_b.resource_ids[0], root_two)
    _bind(admin_conn, tenant_b, tenant_b.resource_ids[1], root_one)

    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    target_start = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)

    original_a, original_b = await asyncio.gather(
        book_appointment(
            reservations,
            _book_command(tenant_a, tenant_a.resource_ids[0], original_start),
        ),
        book_appointment(
            reservations,
            _book_command(tenant_b, tenant_b.resource_ids[0], original_start),
        ),
    )

    barrier = asyncio.Barrier(2)
    original_locker = cast(
        SharedRootLocker,
        reservation_db.__dict__["_lock_shared_capacity_roots"],
    )

    async def synchronized_locker(
        session: AsyncSession,
        organization_id: UUID,
        resource_ids: tuple[UUID, ...],
    ) -> None:
        await asyncio.wait_for(barrier.wait(), timeout=5)
        await original_locker(session, organization_id, resource_ids)

    monkeypatch.setattr(
        reservation_db,
        "_lock_shared_capacity_roots",
        synchronized_locker,
    )

    rescheduled_a, rescheduled_b = await asyncio.wait_for(
        asyncio.gather(
            reschedule_reservation(
                commitments,
                _reschedule_command(
                    tenant_a,
                    reservation_id=original_a.id,
                    expected_revision=original_a.revision,
                    resource_id=tenant_a.resource_ids[1],
                    start_at=target_start,
                ),
            ),
            reschedule_reservation(
                commitments,
                _reschedule_command(
                    tenant_b,
                    reservation_id=original_b.id,
                    expected_revision=original_b.revision,
                    resource_id=tenant_b.resource_ids[1],
                    start_at=target_start,
                ),
            ),
        ),
        timeout=10,
    )

    assert rescheduled_a.start_at == target_start
    assert rescheduled_b.start_at == target_start
    assert rescheduled_a.revision == original_a.revision + 1
    assert rescheduled_b.revision == original_b.revision + 1

    rows = admin_conn.execute(
        """
        SELECT c.reservation_id, c.resource_id, link.shared_capacity_identity_id
        FROM request_engine.capacity_claims c
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE c.reservation_id = ANY(%s::uuid[])
          AND c.status = 'active'
        ORDER BY c.reservation_id
        """,
        ([original_a.id, original_b.id],),
    ).fetchall()
    assert {(cast(UUID, row[0]), cast(UUID, row[1]), cast(UUID, row[2])) for row in rows} == {
        (original_a.id, tenant_a.resource_ids[1], root_two),
        (original_b.id, tenant_b.resource_ids[1], root_one),
    }

    states = admin_conn.execute(
        """
        SELECT status, count(*)
        FROM request_engine.capacity_claims
        WHERE reservation_id = ANY(%s::uuid[])
        GROUP BY status
        ORDER BY status
        """,
        ([original_a.id, original_b.id],),
    ).fetchall()
    assert {cast(str, row[0]): cast(int, row[1]) for row in states} == {
        "active": 2,
        "replaced": 2,
    }
