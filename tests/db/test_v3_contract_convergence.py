from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"contract-{suffix}", f"Contract {suffix}"),
    )


def _party(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {uuid4().hex}"),
    )


def _offering_version(
    conn: PgConnection,
    organization_id: UUID,
    *,
    bookable: bool = True,
) -> UUID:
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'Contract convergence offering')
        RETURNING id
        """,
        (organization_id, f"offering-{uuid4().hex}"),
    )
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 60, %s)
        RETURNING id
        """,
        (organization_id, offering_id, bookable),
    )


def _capacity_fixture(conn: PgConnection) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    organization_id = _organization(conn)
    subject_id = _party(conn, organization_id)
    version_id = _offering_version(conn, organization_id)
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Capacity capability')
        RETURNING id
        """,
        (organization_id, f"capability-{uuid4().hex}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Capacity resource', 'units', 2)
        RETURNING id
        """,
        (organization_id, f"resource-{uuid4().hex}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    return organization_id, subject_id, version_id, requirement_id, resource_id


def _reservation_with_claim(
    conn: PgConnection,
    fixture: tuple[UUID, UUID, UUID, UUID, UUID],
    during: str,
) -> UUID:
    organization_id, subject_id, version_id, requirement_id, resource_id = fixture
    with conn.transaction():
        reservation_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during
            ) VALUES (%s, %s, %s, %s::tstzrange)
            RETURNING id
            """,
            (organization_id, version_id, subject_id, during),
        )
        conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id,
                reservation_id, during, quantity
            ) VALUES (%s, %s, %s, %s, %s::tstzrange, 1)
            """,
            (organization_id, resource_id, requirement_id, reservation_id, during),
        )
    return reservation_id


@pytest.mark.postgres
def test_zero_requirement_offering_cannot_commit_confirmed_reservation(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    subject_id = _party(admin_conn, organization_id)
    version_id = _offering_version(admin_conn, organization_id)

    with pytest.raises(Error) as exc_info, admin_conn.transaction():
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during
            ) VALUES (
                %s, %s, %s,
                '[2099-01-01 10:00+00,2099-01-01 11:00+00)'::tstzrange
            )
            """,
            (organization_id, version_id, subject_id),
        )
    assert exc_info.value.sqlstate == "23514"


@pytest.mark.postgres
def test_zero_requirement_offering_cannot_commit_live_hold(admin_conn: PgConnection) -> None:
    organization_id = _organization(admin_conn)
    subject_id = _party(admin_conn, organization_id)
    version_id = _offering_version(admin_conn, organization_id)

    with pytest.raises(Error) as exc_info, admin_conn.transaction():
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id, during, expires_at
            ) VALUES (
                %s, %s, %s,
                '[2099-01-01 10:00+00,2099-01-01 11:00+00)'::tstzrange,
                clock_timestamp() + interval '10 minutes'
            )
            """,
            (organization_id, version_id, subject_id),
        )
    assert exc_info.value.sqlstate == "23514"


@pytest.mark.postgres
def test_nonbooking_version_may_have_zero_requirements(admin_conn: PgConnection) -> None:
    organization_id = _organization(admin_conn)
    version_id = _offering_version(admin_conn, organization_id, bookable=False)
    row = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.offering_resource_requirements
        WHERE organization_id = %s AND offering_version_id = %s
        """,
        (organization_id, version_id),
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.postgres
def test_closed_is_not_a_reservation_state(admin_conn: PgConnection) -> None:
    organization_id = _organization(admin_conn)
    subject_id = _party(admin_conn, organization_id)
    version_id = _offering_version(admin_conn, organization_id)

    with pytest.raises(Error) as exc_info:
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during, status
            ) VALUES (
                %s, %s, %s,
                '[2099-01-01 10:00+00,2099-01-01 11:00+00)'::tstzrange,
                'closed'
            )
            """,
            (organization_id, version_id, subject_id),
        )
    assert exc_info.value.sqlstate == "23514"


@pytest.mark.postgres
def test_past_confirmed_reservation_does_not_freeze_resource_maintenance(
    admin_conn: PgConnection,
) -> None:
    fixture = _capacity_fixture(admin_conn)
    organization_id, _, _, _, resource_id = fixture
    _reservation_with_claim(
        admin_conn,
        fixture,
        "[2020-01-01 10:00+00,2020-01-01 11:00+00)",
    )

    admin_conn.execute(
        """
        UPDATE request_engine.resources
        SET capacity_units = 3
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, resource_id),
    )
    row = admin_conn.execute(
        "SELECT capacity_units FROM request_engine.resources WHERE id = %s",
        (resource_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == 3


@pytest.mark.postgres
def test_future_confirmed_reservation_still_blocks_resource_maintenance(
    admin_conn: PgConnection,
) -> None:
    fixture = _capacity_fixture(admin_conn)
    organization_id, _, _, _, resource_id = fixture
    _reservation_with_claim(
        admin_conn,
        fixture,
        "[2099-01-01 10:00+00,2099-01-01 11:00+00)",
    )

    with pytest.raises(Error) as exc_info:
        admin_conn.execute(
            """
            UPDATE request_engine.resources
            SET capacity_units = 3
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, resource_id),
        )
    assert exc_info.value.sqlstate == "55000"


@pytest.mark.postgres
def test_revision_step_is_supplied_when_caller_leaves_revision_unchanged(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    queue_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.service_queues (organization_id, queue_key, display_name)
        VALUES (%s, %s, 'Before')
        RETURNING id
        """,
        (organization_id, f"queue-{uuid4().hex}"),
    )

    row = admin_conn.execute(
        """
        UPDATE request_engine.service_queues
        SET display_name = 'After'
        WHERE organization_id = %s AND id = %s
        RETURNING revision
        """,
        (organization_id, queue_id),
    ).fetchone()
    assert row is not None
    assert row[0] == 2


@pytest.mark.postgres
def test_revision_step_rejects_skips_and_backwards_values(admin_conn: PgConnection) -> None:
    organization_id = _organization(admin_conn)
    queue_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.service_queues (organization_id, queue_key, display_name)
        VALUES (%s, %s, 'Queue')
        RETURNING id
        """,
        (organization_id, f"queue-{uuid4().hex}"),
    )

    with pytest.raises(Error) as skip_error:
        admin_conn.execute(
            """
            UPDATE request_engine.service_queues
            SET revision = revision + 2
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, queue_id),
        )
    assert skip_error.value.sqlstate == "23514"

    with pytest.raises(Error) as backwards_error:
        admin_conn.execute(
            """
            UPDATE request_engine.service_queues
            SET revision = revision - 1
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, queue_id),
        )
    assert backwards_error.value.sqlstate == "23514"


@pytest.mark.postgres
def test_all_revision_managed_aggregates_install_revision_guard(
    admin_conn: PgConnection,
) -> None:
    expected = {
        "representations",
        "requests",
        "capacity_holds",
        "reservations",
        "reservation_attendance",
        "service_queues",
        "queue_entries",
        "waitlist_entries",
        "slot_opportunities",
        "slot_offers",
        "communication_tasks",
        "reminder_plans",
    }
    rows = admin_conn.execute(
        """
        SELECT c.relname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND NOT t.tgisinternal
          AND t.tgname LIKE '%_revision_step'
        """
    ).fetchall()
    assert {cast(str, row[0]) for row in rows} == expected
