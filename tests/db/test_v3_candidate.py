import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


@dataclass(frozen=True)
class BookingFixture:
    organization_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    subject_party_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"org-{suffix}", f"Organization {suffix}"),
    )


def _create_party(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Patient {uuid4().hex}"),
    )


def _create_booking_fixture(
    conn: PgConnection,
    *,
    capacity_model: str = "exclusive",
    capacity_units: int = 1,
    requirement_quantity: int = 1,
) -> BookingFixture:
    organization_id = _create_organization(conn)
    subject_party_id = _create_party(conn, organization_id)

    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{uuid4().hex}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 60, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Doctor')
        RETURNING id
        """,
        (organization_id, f"doctor-{uuid4().hex}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, %s)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id, requirement_quantity),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id,
            resource_key,
            display_name,
            capacity_model,
            capacity_units
        ) VALUES (%s, %s, 'Dr. Resource', %s, %s)
        RETURNING id
        """,
        (organization_id, f"resource-{uuid4().hex}", capacity_model, capacity_units),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )

    return BookingFixture(
        organization_id=organization_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        subject_party_id=subject_party_id,
    )


def _insert_reservation(conn: PgConnection, setup: BookingFixture, during: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.reservations (
            organization_id,
            offering_version_id,
            subject_party_id,
            during
        ) VALUES (%s, %s, %s, %s::tstzrange)
        RETURNING id
        """,
        (
            setup.organization_id,
            setup.offering_version_id,
            setup.subject_party_id,
            during,
        ),
    )


def _insert_claim(
    conn: PgConnection,
    setup: BookingFixture,
    reservation_id: UUID,
    during: str,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.capacity_claims (
            organization_id,
            resource_id,
            requirement_id,
            reservation_id,
            during,
            quantity
        ) VALUES (%s, %s, %s, %s, %s::tstzrange, 1)
        RETURNING id
        """,
        (
            setup.organization_id,
            setup.resource_id,
            setup.requirement_id,
            reservation_id,
            during,
        ),
    )


def _book(conn: PgConnection, setup: BookingFixture, during: str) -> tuple[UUID, UUID]:
    with conn.transaction():
        reservation_id = _insert_reservation(conn, setup, during)
        claim_id = _insert_claim(conn, setup, reservation_id, during)
    return reservation_id, claim_id


def _attempt_concurrent_booking(
    conninfo: str,
    setup: BookingFixture,
    during: str,
    ready: Event,
) -> str:
    conn: PgConnection = psycopg.connect(conninfo)
    try:
        _insert_reservation(conn, setup, during)
        ready.set()
        reservation_row = conn.execute(
            """
            SELECT id
            FROM request_engine.reservations
            WHERE organization_id = %s
              AND subject_party_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (setup.organization_id, setup.subject_party_id),
        ).fetchone()
        assert reservation_row is not None
        reservation_id = cast(UUID, reservation_row[0])
        _insert_claim(conn, setup, reservation_id, during)
        conn.commit()
        return "ok"
    except Error as exc:
        conn.rollback()
        return exc.sqlstate or "postgres-error"
    finally:
        conn.close()


@pytest.mark.postgres
def test_v3_candidate_does_not_recreate_deferred_v2_tables(admin_conn: PgConnection) -> None:
    old_tables = [
        "request_engine.outcome_scopes",
        "request_engine.resource_allocations",
        "request_engine.capacity_authorities",
        "request_engine.payment_transactions",
        "request_engine.dispatches",
    ]
    for table_name in old_tables:
        row = admin_conn.execute("SELECT to_regclass(%s)", (table_name,)).fetchone()
        assert row is not None
        assert row[0] is None


@pytest.mark.postgres
def test_rls_and_security_invoker_view_isolate_tenants(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    org_a = _create_organization(admin_conn)
    org_b = _create_organization(admin_conn)
    _create_party(admin_conn, org_a)
    _create_party(admin_conn, org_b)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, true)",
            (str(org_a),),
        )

        organization_rows = app_conn.execute(
            "SELECT id FROM request_engine.organizations ORDER BY id"
        ).fetchall()
        assert [row[0] for row in organization_rows] == [org_a]

        view_rows = app_conn.execute(
            "SELECT organization_id FROM request_read.business_info_v1"
        ).fetchall()
        assert [row[0] for row in view_rows] == [org_a]

        with pytest.raises(Error) as exc_info:
            app_conn.execute(
                """
                INSERT INTO request_engine.parties (
                    organization_id, party_kind, display_name
                ) VALUES (%s, 'person', 'Cross tenant')
                """,
                (org_b,),
            )
        assert exc_info.value.sqlstate == "42501"
    finally:
        app_conn.rollback()
        app_conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_concurrent_exclusive_booking_cannot_double_book(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = _create_booking_fixture(admin_conn)
    during = "[2026-08-20 14:00+00,2026-08-20 15:00+00)"

    first: PgConnection = psycopg.connect(pg_conninfo)
    try:
        first_reservation = _insert_reservation(first, setup, during)
        _insert_claim(first, setup, first_reservation, during)

        ready = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _attempt_concurrent_booking,
                pg_conninfo,
                setup,
                during,
                ready,
            )
            assert ready.wait(timeout=5)
            time.sleep(0.05)
            first.commit()
            assert future.result(timeout=5) == "23P01"
    finally:
        first.rollback()
        first.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_concurrent_units_booking_cannot_oversell(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = _create_booking_fixture(admin_conn, capacity_model="units", capacity_units=2)
    during = "[2026-08-21 14:00+00,2026-08-21 15:00+00)"
    _book(admin_conn, setup, during)

    second: PgConnection = psycopg.connect(pg_conninfo)
    try:
        second_reservation = _insert_reservation(second, setup, during)
        _insert_claim(second, setup, second_reservation, during)

        ready = Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _attempt_concurrent_booking,
                pg_conninfo,
                setup,
                during,
                ready,
            )
            assert ready.wait(timeout=5)
            time.sleep(0.05)
            second.commit()
            assert future.result(timeout=5) == "23P01"
    finally:
        second.rollback()
        second.close()


@pytest.mark.postgres
def test_overlapping_self_reschedule_replaces_own_claim_without_double_counting(
    admin_conn: PgConnection,
) -> None:
    setup = _create_booking_fixture(admin_conn)
    old_during = "[2026-08-22 10:00+00,2026-08-22 11:00+00)"
    new_during = "[2026-08-22 10:30+00,2026-08-22 11:30+00)"
    reservation_id, old_claim_id = _book(admin_conn, setup, old_during)

    with admin_conn.transaction():
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
               SET status = 'released',
                   released_at = clock_timestamp()
             WHERE id = %s
            """,
            (old_claim_id,),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.reservations
               SET during = %s::tstzrange,
                   revision = revision + 1
             WHERE id = %s
            """,
            (new_during, reservation_id),
        )
        new_claim_id = _insert_claim(admin_conn, setup, reservation_id, new_during)
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
               SET status = 'replaced',
                   replaced_by_claim_id = %s
             WHERE id = %s
            """,
            (new_claim_id, old_claim_id),
        )

    rows = admin_conn.execute(
        """
        SELECT id, status
        FROM request_engine.capacity_claims
        WHERE reservation_id = %s
        ORDER BY created_at, id
        """,
        (reservation_id,),
    ).fetchall()
    assert {row[1] for row in rows} == {"active", "replaced"}


@pytest.mark.postgres
def test_expired_hold_cannot_be_promoted_to_reservation(admin_conn: PgConnection) -> None:
    setup = _create_booking_fixture(admin_conn)
    during = "[2026-08-23 10:00+00,2026-08-23 11:00+00)"

    with admin_conn.transaction():
        hold_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id,
                offering_version_id,
                subject_party_id,
                during,
                expires_at
            ) VALUES (%s, %s, %s, %s::tstzrange, clock_timestamp() + interval '1 hour')
            RETURNING id
            """,
            (
                setup.organization_id,
                setup.offering_version_id,
                setup.subject_party_id,
                during,
            ),
        )
        claim_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id,
                resource_id,
                requirement_id,
                hold_id,
                during,
                quantity
            ) VALUES (%s, %s, %s, %s, %s::tstzrange, 1)
            RETURNING id
            """,
            (
                setup.organization_id,
                setup.resource_id,
                setup.requirement_id,
                hold_id,
                during,
            ),
        )

    admin_conn.execute(
        """
        UPDATE request_engine.capacity_holds
           SET expires_at = created_at + interval '1 millisecond'
         WHERE id = %s
        """,
        (hold_id,),
    )

    with pytest.raises(Error) as exc_info, admin_conn.transaction():
        reservation_id = _insert_reservation(admin_conn, setup, during)
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
               SET reservation_id = %s
             WHERE id = %s
            """,
            (reservation_id, claim_id),
        )
    assert exc_info.value.sqlstate == "23514"


@pytest.mark.postgres
def test_queue_allows_only_one_active_entry_per_subject(admin_conn: PgConnection) -> None:
    organization_id = _create_organization(admin_conn)
    subject_party_id = _create_party(admin_conn, organization_id)
    queue_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name
        ) VALUES (%s, %s, 'Walk-in')
        RETURNING id
        """,
        (organization_id, f"queue-{uuid4().hex}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, queue_id, subject_party_id),
    )

    with pytest.raises(Error) as exc_info:
        admin_conn.execute(
            """
            INSERT INTO request_engine.queue_entries (
                organization_id, service_queue_id, subject_party_id
            ) VALUES (%s, %s, %s)
            """,
            (organization_id, queue_id, subject_party_id),
        )
    assert exc_info.value.sqlstate == "23505"


@pytest.mark.postgres
@pytest.mark.concurrency
def test_scheduled_action_fencing_rejects_stale_worker(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _create_organization(admin_conn)
    action_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at
        ) VALUES (
            %s,
            'communications',
            'send_reminder.v1',
            '{}'::jsonb,
            %s,
            clock_timestamp(),
            '-infinity'::timestamptz
        )
        RETURNING id
        """,
        (organization_id, f"action-{uuid4().hex}"),
    )

    worker: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        first_claim = worker.execute(
            "SELECT action_id, organization_id, claim_token "
            "FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
        ).fetchone()
        assert first_claim is not None
        assert first_claim[0] == action_id
        assert first_claim[1] == organization_id
        first_token = cast(UUID, first_claim[2])

        admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
               -- This database-level test shares a candidate database with other
               -- tests that may leave legitimate due work behind. Make this row
               -- deterministically first without claiming or mutating unrelated
               -- tenants' work.
               SET lease_until = '-infinity'::timestamptz
             WHERE id = %s
            """,
            (action_id,),
        )

        second_claim = worker.execute(
            "SELECT action_id, claim_token "
            "FROM request_cmd.claim_scheduled_actions(1, interval '30 seconds')"
        ).fetchone()
        assert second_claim is not None
        assert second_claim[0] == action_id
        second_token = cast(UUID, second_claim[1])
        assert second_token != first_token

        stale_result = worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, first_token),
        ).fetchone()
        assert stale_result is not None
        assert stale_result[0] is False

        current_result = worker.execute(
            "SELECT request_cmd.complete_scheduled_action(%s, %s)",
            (action_id, second_token),
        ).fetchone()
        assert current_result is not None
        assert current_result[0] is True
    finally:
        worker.close()


@pytest.mark.postgres
def test_worker_roles_do_not_bypass_rls_and_claim_function_pins_search_path(
    admin_conn: PgConnection,
) -> None:
    role_rows = admin_conn.execute(
        """
        SELECT rolname, rolbypassrls
        FROM pg_roles
        WHERE rolname IN ('request_engine_app', 'request_engine_worker')
        ORDER BY rolname
        """
    ).fetchall()
    assert role_rows == [
        ("request_engine_app", False),
        ("request_engine_worker", False),
    ]

    config_row = admin_conn.execute(
        """
        SELECT proconfig
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'request_cmd'
          AND p.proname = 'claim_scheduled_actions'
        """
    ).fetchone()
    assert config_row is not None
    assert "search_path=pg_catalog, request_engine" in cast(list[str], config_row[0])
