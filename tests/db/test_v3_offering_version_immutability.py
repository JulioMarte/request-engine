from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
def test_i07_referenced_offering_version_is_an_immutable_historical_snapshot(
    admin_conn: PgConnection,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i07-{suffix}", f"I07 {suffix}"),
    )
    party_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    offering_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"offering-{suffix}", f"Offering {suffix}"),
    )
    offering_version_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy, public_data
        ) VALUES (
            %s, %s, 1, 30, true, true,
            '{"slot_step_minutes": 30}'::jsonb,
            '{"label": "historical-v1"}'::jsonb
        )
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    reservation_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.reservations (
            organization_id, offering_version_id, subject_party_id,
            during, booking_policy_snapshot
        ) VALUES (
            %s, %s, %s,
            tstzrange(
                clock_timestamp() + interval '1 day',
                clock_timestamp() + interval '1 day 30 minutes',
                '[)'
            ),
            '{"slot_step_minutes": 30}'::jsonb
        )
        RETURNING id
        """,
        (organization_id, offering_version_id, party_id),
    )

    with pytest.raises(Error) as update_error:
        admin_conn.execute(
            """
            UPDATE request_engine.offering_versions
            SET duration_minutes = 60,
                public_data = '{"label": "mutated"}'::jsonb
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, offering_version_id),
        )
    assert update_error.value.sqlstate == "55000"

    with pytest.raises(Error) as delete_error:
        admin_conn.execute(
            """
            DELETE FROM request_engine.offering_versions
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, offering_version_id),
        )
    assert delete_error.value.sqlstate == "55000"

    snapshot = admin_conn.execute(
        """
        SELECT version, duration_minutes, booking_policy, public_data
        FROM request_engine.offering_versions
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, offering_version_id),
    ).fetchone()
    assert snapshot == (
        1,
        30,
        {"slot_step_minutes": 30},
        {"label": "historical-v1"},
    )
    assert admin_conn.execute(
        """
        SELECT offering_version_id
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, reservation_id),
    ).fetchone() == (offering_version_id,)
