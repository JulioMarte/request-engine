from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class DiscoveryFixture:
    organization_id: UUID
    party_id: UUID
    location_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    mapping_id: UUID
    publication_id: UUID


def uuid_row(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_discovery_fixture(conn: PgConnection) -> DiscoveryFixture:
    suffix = uuid4().hex
    organization_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Discovery Org')
        RETURNING id
        """,
        (f"org-{suffix}",),
    )
    party_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Subject')
        RETURNING id
        """,
        (organization_id,),
    )
    location_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, latitude, longitude
        ) VALUES (%s, %s, 'Clinic', 'UTC', 19.8, -70.7)
        RETURNING id
        """,
        (organization_id, f"loc-{suffix}"),
    )
    offering_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Cardiology')
        RETURNING id
        """,
        (organization_id, f"offering-{suffix}"),
    )
    version_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
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
        (organization_id, version_id, capability_id),
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
    classification_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_classifications (
            classification_key, canonical_name
        ) VALUES (%s, 'Cardiology')
        RETURNING id
        """,
        (f"cardiology_{suffix}",),
    )
    mapping_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_service_classifications (
            organization_id, offering_id, service_classification_id
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, offering_id, classification_id),
    )
    publication_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.discovery_publications (
            organization_id, offering_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2035-01-01T00:00:00+00', '2036-01-01T00:00:00+00', '[)')
        )
        RETURNING id
        """,
        (organization_id, offering_id, location_id),
    )
    return DiscoveryFixture(
        organization_id,
        party_id,
        location_id,
        offering_id,
        version_id,
        requirement_id,
        resource_id,
        mapping_id,
        publication_id,
    )
