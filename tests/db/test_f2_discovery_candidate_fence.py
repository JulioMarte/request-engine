from typing import Any
from uuid import uuid4

import psycopg
import pytest
from f2_discovery_fixture import create_discovery_fixture, uuid_row
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
@pytest.mark.security
def test_mapping_change_after_search_prevents_handoff_issuance(
    admin_conn: PgConnection,
) -> None:
    fixture = create_discovery_fixture(admin_conn)
    replacement_classification = uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.service_classifications (
            classification_key, canonical_name
        ) VALUES (%s, 'Dermatology') RETURNING id
        """,
        (f"dermatology_{uuid4().hex}",),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.offering_service_classifications
        SET status = 'revoked'
        WHERE id = %s
        """,
        (fixture.mapping_id,),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.offering_service_classifications (
            organization_id, offering_id, service_classification_id
        ) VALUES (%s, %s, %s)
        """,
        (fixture.organization_id, fixture.offering_id, replacement_classification),
    )
    selection = f"""
    {{
      "offering_version_id":"{fixture.offering_version_id}",
      "location_id":"{fixture.location_id}",
      "start_at":"2035-06-01T14:00:00+00:00",
      "end_at":"2035-06-01T14:30:00+00:00",
      "resources":[{{"resource_id":"{uuid4()}"}}],
      "planned_duration_minutes":30,
      "amount":"3500",
      "currency":"DOP",
      "location_operational_revision":1,
      "configuration_fingerprint":"sha256:test"
    }}
    """
    with pytest.raises(psycopg.errors.SerializationFailure), admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT request_engine.issue_discovery_booking_handoff(
                repeat('d', 64), %s, 1, %s, 1, %s, %s, %s::jsonb,
                clock_timestamp() + interval '10 minutes'
            )
            """,
            (
                fixture.publication_id,
                fixture.mapping_id,
                fixture.offering_version_id,
                fixture.location_id,
                selection,
            ),
        )
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.discovery_booking_handoffs
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone() == (0,)
