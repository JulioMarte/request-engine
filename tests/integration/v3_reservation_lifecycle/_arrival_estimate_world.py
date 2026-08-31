from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class ArrivalWorld:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID


def _uuid_row(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_arrival_world(conn: PgConnection, *, status: str = "confirmed") -> ArrivalWorld:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.organizations (organization_key, display_name)"
        " VALUES (%s, %s) RETURNING id",
        (f"arrival-{suffix}", f"Arrival {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals (organization_id, principal_kind, external_subject)"
        " VALUES (%s, 'agent', %s) RETURNING id",
        (organization_id, f"agent-{suffix}"),
    )
    subject_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.parties (organization_id, party_kind, display_name)"
        " VALUES (%s, 'person', %s) RETURNING id",
        (organization_id, f"Subject {suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)"
        " VALUES (%s, %s, 'Consultation') RETURNING id",
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.offering_versions (organization_id, offering_id, version,"
        " duration_minutes, bookable, booking_policy)"
        " VALUES (%s, %s, 1, 30, true, '{}'::jsonb) RETURNING id",
        (organization_id, offering_id),
    )
    capability_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.resource_capabilities (organization_id, capability_key,"
        " display_name) VALUES (%s, %s, 'Doctor') RETURNING id",
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.offering_resource_requirements (organization_id,"
        " offering_version_id, capability_id, ordinal, quantity)"
        " VALUES (%s, %s, %s, 1, 1) RETURNING id",
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.resources (organization_id, resource_key, display_name,"
        " capacity_model, capacity_units) VALUES (%s, %s, 'Doctor', 'exclusive', 1) RETURNING id",
        (organization_id, f"doctor-{suffix}"),
    )
    conn.execute(
        "INSERT INTO request_engine.resource_capability_assignments (organization_id, resource_id,"
        " capability_id) VALUES (%s, %s, %s)",
        (organization_id, resource_id, capability_id),
    )
    start_at = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=3)
    end_at = start_at + timedelta(minutes=30)
    with conn.transaction():
        reservation_id = _uuid_row(
            conn,
            "INSERT INTO request_engine.reservations (organization_id, offering_version_id,"
            " subject_party_id, during)"
            " VALUES (%s, %s, %s, tstzrange(%s, %s, '[)')) RETURNING id",
            (organization_id, offering_version_id, subject_id, start_at, end_at),
        )
        conn.execute(
            "INSERT INTO request_engine.capacity_claims (organization_id, resource_id,"
            " requirement_id, reservation_id, during, quantity)"
            " VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), 1)",
            (organization_id, resource_id, requirement_id, reservation_id, start_at, end_at),
        )
    if status != "confirmed":
        with conn.transaction():
            conn.execute(
                "UPDATE request_engine.capacity_claims SET status = 'released',"
                " released_at = clock_timestamp()"
                " WHERE organization_id = %s AND reservation_id = %s",
                (organization_id, reservation_id),
            )
            conn.execute(
                "UPDATE request_engine.reservations SET status = %s,"
                " cancelled_at = clock_timestamp()"
                " WHERE organization_id = %s AND id = %s",
                (status, organization_id, reservation_id),
            )
    return ArrivalWorld(organization_id, principal_id, reservation_id)


def reservation_revision(conn: PgConnection, world: ArrivalWorld) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.reservations WHERE organization_id = %s AND id = %s",
        (world.organization_id, world.reservation_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
