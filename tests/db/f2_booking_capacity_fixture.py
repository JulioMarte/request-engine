from typing import Any
from uuid import UUID

from psycopg import Connection

from f2_discovery_fixture import uuid_row

PgConnection = Connection[Any]


def create_booking_capacity(
    conn: PgConnection,
    organization_id: UUID,
    offering_version_id: UUID,
    suffix: str,
) -> tuple[UUID, UUID]:
    capability_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Doctor')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Doctor', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    return requirement_id, resource_id
