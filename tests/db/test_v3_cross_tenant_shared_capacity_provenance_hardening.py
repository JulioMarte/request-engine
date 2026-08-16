from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
def test_authority_event_stamps_database_and_request_actor_context(
    admin_conn: PgConnection,
) -> None:
    session_user_row = admin_conn.execute("SELECT session_user").fetchone()
    assert session_user_row is not None
    database_session_user = cast(str, session_user_row[0])
    principal_id = uuid4()
    correlation_id = uuid4()

    admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    admin_conn.execute(
        "SELECT set_config('request_engine.correlation_id', %s, false)",
        (str(correlation_id),),
    )
    admin_conn.execute("SELECT set_config('request_engine.principal_kind', 'operator', false)")
    admin_conn.execute("SELECT set_config('request_engine.authentication_method', 'oidc', false)")

    identity_id = _uuid(
        admin_conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("caller-supplied-label", "verified identity"),
    )
    row = admin_conn.execute(
        """
        SELECT authority_ref, details
        FROM request_engine.shared_capacity_authority_events
        WHERE event_kind = 'global_identity.created'
          AND global_identity_id = %s
        """,
        (identity_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "caller-supplied-label"
    details = cast(dict[str, object], row[1])
    assert details["database_session_user"] == database_session_user
    assert details["authenticated_principal_id"] == str(principal_id)
    assert details["correlation_id"] == str(correlation_id)
    assert details["principal_kind"] == "operator"
    assert details["authentication_method"] == "oidc"


@pytest.mark.postgres
def test_reservation_claim_cannot_replace_itself(admin_conn: PgConnection) -> None:
    suffix = uuid4().hex
    organization_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"replacement-{suffix}", f"Replacement {suffix}"),
    )
    party_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Subject') RETURNING id
        """,
        (organization_id,),
    )
    offering_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'Consult') RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true) RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Provider') RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    requirement_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid(
        admin_conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Provider', 'exclusive', 1) RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )

    with pytest.raises(Error) as invalid_replacement, admin_conn.transaction():
        reservation_id = _uuid(
            admin_conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during
            ) VALUES (
                %s, %s, %s,
                tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                          '2030-08-01T14:30:00+00'::timestamptz, '[)')
            ) RETURNING id
            """,
            (organization_id, offering_version_id, party_id),
        )
        claim_id = _uuid(
            admin_conn,
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id,
                reservation_id, during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2030-08-01T14:00:00+00'::timestamptz,
                          '2030-08-01T14:30:00+00'::timestamptz, '[)'), 1
            ) RETURNING id
            """,
            (organization_id, resource_id, requirement_id, reservation_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp()
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, claim_id),
        )
        admin_conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'replaced', replaced_by_claim_id = id
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, claim_id),
        )
    assert invalid_replacement.value.sqlstate == "23514"
    assert "replacement provenance is invalid" in str(invalid_replacement.value)
