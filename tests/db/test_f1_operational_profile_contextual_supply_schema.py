from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class Fixture:
    organization_id: UUID
    party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    assignment_id: UUID


def _uuid(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> Fixture:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (suffix, f"Organization {suffix}"),
    )
    party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s) RETURNING id
        """,
        (organization_id, f"Party {suffix}"),
    )
    location_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo') RETURNING id
        """,
        (organization_id, f"location-{suffix}", f"Location {suffix}"),
    )
    offering_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"offering-{suffix}", f"Offering {suffix}"),
    )
    offering_version_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true) RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s) RETURNING id
        """,
        (organization_id, f"capability-{suffix}", f"Capability {suffix}"),
    )
    requirement_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1) RETURNING id
        """,
        (organization_id, f"resource-{suffix}", f"Resource {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    assignment_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        ) RETURNING id
        """,
        (organization_id, resource_id, location_id),
    )
    return Fixture(
        organization_id=organization_id,
        party_id=party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        assignment_id=assignment_id,
    )


def _revision(conn: PgConnection, table: str, row_id: UUID, column: str) -> int:
    allowed = {
        ("locations", "operational_revision"),
        ("resources", "availability_revision"),
        ("resource_location_assignments", "revision"),
        ("booking_context_terms", "revision"),
    }
    assert (table, column) in allowed
    row = conn.execute(
        f"SELECT {column} FROM request_engine.{table} WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.postgres
def test_f1_structural_constraints_and_multi_location_assignment(
    admin_conn: PgConnection,
) -> None:
    first = _fixture(admin_conn, "structure")

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.locations (
                organization_id, location_key, display_name, timezone, latitude
            ) VALUES (%s, %s, 'Invalid Coordinates', 'UTC', 18.5)
            """,
            (first.organization_id, f"invalid-{uuid4().hex}"),
        )

    with pytest.raises(psycopg.errors.ExclusionViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.resource_location_assignments (
                organization_id, resource_id, location_id, effective_during
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-02-01T00:00:00+00'::timestamptz,
                          '2030-03-01T00:00:00+00'::timestamptz, '[)')
            )
            """,
            (first.organization_id, first.resource_id, first.location_id),
        )

    second_location_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Second Location', 'America/Santo_Domingo')
        RETURNING id
        """,
        (first.organization_id, f"second-{uuid4().hex}"),
    )
    second_assignment_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        ) RETURNING id
        """,
        (first.organization_id, first.resource_id, second_location_id),
    )
    assert second_assignment_id != first.assignment_id

    foreign = _fixture(admin_conn, "foreign")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.resource_location_assignments (
                organization_id, resource_id, location_id, effective_during
            ) VALUES (
                %s, %s, %s,
                tstzrange('2040-01-01T00:00:00+00'::timestamptz, NULL, '[)')
            )
            """,
            (first.organization_id, first.resource_id, foreign.location_id),
        )


@pytest.mark.postgres
def test_f1_location_and_resource_change_tokens_follow_material_child_state(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn, "revisions")

    location_before = _revision(
        admin_conn,
        "locations",
        fixture.location_id,
        "operational_revision",
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (fixture.organization_id, fixture.location_id),
    )
    location_after_hours = _revision(
        admin_conn,
        "locations",
        fixture.location_id,
        "operational_revision",
    )
    assert location_after_hours > location_before

    admin_conn.execute(
        """
        INSERT INTO request_engine.location_hours_exceptions (
            organization_id, location_id, during, exception_kind
        ) VALUES (
            %s, %s,
            tstzrange('2030-05-06T12:00:00+00'::timestamptz,
                      '2030-05-06T13:00:00+00'::timestamptz, '[)'),
            'unavailable'
        )
        """,
        (fixture.organization_id, fixture.location_id),
    )
    location_after_exception = _revision(
        admin_conn,
        "locations",
        fixture.location_id,
        "operational_revision",
    )
    assert location_after_exception > location_after_hours

    resource_before = _revision(
        admin_conn,
        "resources",
        fixture.resource_id,
        "availability_revision",
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '16:00')
        """,
        (fixture.organization_id, fixture.assignment_id),
    )
    resource_after_hours = _revision(
        admin_conn,
        "resources",
        fixture.resource_id,
        "availability_revision",
    )
    assert resource_after_hours > resource_before

    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_location_schedule_exceptions (
            organization_id, resource_location_assignment_id, during, exception_kind
        ) VALUES (
            %s, %s,
            tstzrange('2030-05-06T14:00:00+00'::timestamptz,
                      '2030-05-06T15:00:00+00'::timestamptz, '[)'),
            'unavailable'
        )
        """,
        (fixture.organization_id, fixture.assignment_id),
    )
    resource_after_exception = _revision(
        admin_conn,
        "resources",
        fixture.resource_id,
        "availability_revision",
    )
    assert resource_after_exception > resource_after_hours


@pytest.mark.postgres
def test_f1_context_terms_are_effective_dated_and_do_not_broadly_stale_resource(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn, "terms")
    base_terms_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP') RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id),
    )
    assert base_terms_id

    context_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id,
            offering_version_id, effective_during,
            amount, currency, planned_duration_minutes
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-01-01T00:00:00+00'::timestamptz,
                      '2031-01-01T00:00:00+00'::timestamptz, '[)'),
            4000, 'DOP', 45
        ) RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.assignment_id,
            fixture.offering_version_id,
        ),
    )

    with pytest.raises(psycopg.errors.ExclusionViolation):
        admin_conn.execute(
            """
            INSERT INTO request_engine.booking_context_terms (
                organization_id, resource_location_assignment_id,
                offering_version_id, effective_during,
                amount, currency
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-06-01T00:00:00+00'::timestamptz,
                          '2030-07-01T00:00:00+00'::timestamptz, '[)'),
                4200, 'DOP'
            )
            """,
            (
                fixture.organization_id,
                fixture.assignment_id,
                fixture.offering_version_id,
            ),
        )

    admin_conn.execute(
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id,
            offering_version_id, effective_during,
            amount, currency, active
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-06-01T00:00:00+00'::timestamptz,
                      '2030-07-01T00:00:00+00'::timestamptz, '[)'),
            4200, 'DOP', false
        )
        """,
        (
            fixture.organization_id,
            fixture.assignment_id,
            fixture.offering_version_id,
        ),
    )

    resource_before = _revision(
        admin_conn,
        "resources",
        fixture.resource_id,
        "availability_revision",
    )
    context_before = _revision(
        admin_conn,
        "booking_context_terms",
        context_id,
        "revision",
    )
    admin_conn.execute(
        """
        UPDATE request_engine.booking_context_terms
           SET amount = 4100
         WHERE organization_id = %s
           AND id = %s
        """,
        (fixture.organization_id, context_id),
    )
    context_after = _revision(
        admin_conn,
        "booking_context_terms",
        context_id,
        "revision",
    )
    resource_after = _revision(
        admin_conn,
        "resources",
        fixture.resource_id,
        "availability_revision",
    )
    assert context_after == context_before + 1
    assert resource_after == resource_before


@pytest.mark.postgres
def test_f1_contextual_claim_provenance_and_commercial_commitment_are_durable(
    admin_conn: PgConnection,
) -> None:
    fixture = _fixture(admin_conn, "provenance")
    base_terms_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP') RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id),
    )

    with admin_conn.transaction():
        reservation_id = _uuid(
            admin_conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id,
                location_id, during
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2030-06-03T14:00:00+00'::timestamptz,
                          '2030-06-03T14:30:00+00'::timestamptz, '[)')
            ) RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.party_id,
                fixture.location_id,
            ),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id,
                reservation_id, resource_location_assignment_id,
                during, quantity
            ) VALUES (
                %s, %s, %s, %s, %s,
                tstzrange('2030-06-03T14:00:00+00'::timestamptz,
                          '2030-06-03T14:30:00+00'::timestamptz, '[)'),
                1
            )
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                reservation_id,
                fixture.assignment_id,
            ),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservation_commercial_commitments (
                reservation_id, organization_id,
                offering_version_booking_terms_id,
                amount, currency, planned_duration_minutes,
                configuration_fingerprint
            ) VALUES (%s, %s, %s, 3500, 'DOP', 30, %s)
            """,
            (
                reservation_id,
                fixture.organization_id,
                base_terms_id,
                f"test-fingerprint-{uuid4().hex}",
            ),
        )

    row = admin_conn.execute(
        """
        SELECT amount, currency, planned_duration_minutes
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert row is not None
    assert row[0] == 3500
    assert row[1] == "DOP"
    assert row[2] == 30

    with pytest.raises(psycopg.Error) as immutable:
        admin_conn.execute(
            """
            UPDATE request_engine.reservation_commercial_commitments
               SET amount = 9999
             WHERE organization_id = %s AND reservation_id = %s
            """,
            (fixture.organization_id, reservation_id),
        )
    assert immutable.value.sqlstate == "55000"

    other = _fixture(admin_conn, "wrong-assignment")
    with pytest.raises(psycopg.errors.CheckViolation):
        with admin_conn.transaction():
            hold_id = _uuid(
                admin_conn,
                """
                INSERT INTO request_engine.capacity_holds (
                    organization_id, offering_version_id, subject_party_id,
                    location_id, during, expires_at
                ) VALUES (
                    %s, %s, %s, %s,
                    tstzrange('2030-06-04T14:00:00+00'::timestamptz,
                              '2030-06-04T14:30:00+00'::timestamptz, '[)'),
                    clock_timestamp() + interval '1 hour'
                ) RETURNING id
                """,
                (
                    fixture.organization_id,
                    fixture.offering_version_id,
                    fixture.party_id,
                    fixture.location_id,
                ),
            )
            admin_conn.execute(
                """
                INSERT INTO request_engine.capacity_claims (
                    organization_id, resource_id, requirement_id,
                    hold_id, resource_location_assignment_id,
                    during, quantity
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    tstzrange('2030-06-04T14:00:00+00'::timestamptz,
                              '2030-06-04T14:30:00+00'::timestamptz, '[)'),
                    1
                )
                """,
                (
                    fixture.organization_id,
                    fixture.resource_id,
                    fixture.requirement_id,
                    hold_id,
                    other.assignment_id,
                ),
            )


@pytest.mark.postgres
def test_f1_new_tables_force_rls_and_do_not_leak_foreign_tenant_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    first = _fixture(admin_conn, "rls-a")
    second = _fixture(admin_conn, "rls-b")
    first_endpoint = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.organization_public_contact_endpoints (
            organization_id, channel, normalized_value
        ) VALUES (%s, 'phone', %s) RETURNING id
        """,
        (first.organization_id, f"+1809{uuid4().int % 10_000_000:07d}"),
    )
    _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.organization_public_contact_endpoints (
            organization_id, channel, normalized_value
        ) VALUES (%s, 'phone', %s) RETURNING id
        """,
        (second.organization_id, f"+1829{uuid4().int % 10_000_000:07d}"),
    )

    rls_rows = admin_conn.execute(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND relname = ANY(%s::text[])
        ORDER BY relname
        """,
        (
            [
                "organization_public_contact_endpoints",
                "location_public_contact_endpoints",
                "location_operational_hours",
                "location_hours_exceptions",
                "resource_location_assignments",
                "resource_location_availability",
                "resource_location_schedule_exceptions",
                "offering_version_booking_terms",
                "booking_context_terms",
                "reservation_commercial_commitments",
            ],
        ),
    ).fetchall()
    assert len(rls_rows) == 10
    assert all(cast(bool, row[1]) and cast(bool, row[2]) for row in rls_rows)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(first.organization_id),),
        )
        rows = app_conn.execute(
            """
            SELECT id, organization_id
            FROM request_engine.organization_public_contact_endpoints
            ORDER BY id
            """
        ).fetchall()
        assert rows == [(first_endpoint, first.organization_id)]

        with pytest.raises(psycopg.Error) as denied:
            app_conn.execute(
                """
                INSERT INTO request_engine.organization_public_contact_endpoints (
                    organization_id, channel, normalized_value
                ) VALUES (%s, 'email', %s)
                """,
                (second.organization_id, f"foreign-{uuid4().hex}@example.test"),
            )
        assert denied.value.sqlstate == "42501"
        app_conn.rollback()
    finally:
        app_conn.close()
