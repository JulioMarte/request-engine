from uuid import UUID, uuid4

from .operational_support import PgConnection


def seed_second_location_assignment(
    conn: PgConnection,
    organization_id: UUID,
    resource_id: UUID,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, 'North Clinic', 'America/Santo_Domingo', '{}'::jsonb)
        RETURNING id
        """,
        (organization_id, f"north-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    location_id = row[0]
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (%s, %s, %s, tstzrange(clock_timestamp() - interval '1 day', NULL, '[)'))
        """,
        (organization_id, resource_id, location_id),
    )
    return location_id
