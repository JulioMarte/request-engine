from typing import Any, LiteralString, cast
from uuid import UUID

from psycopg import Connection

PgConnection = Connection[Any]


def uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_workload(conn: PgConnection, org: UUID, key: str, name: str) -> UUID:
    return uuid_row(
        conn,
        "INSERT INTO request_engine.operational_workload_classifications "
        "(organization_id,workload_key,display_name) VALUES (%s,%s,%s) RETURNING id",
        (org, key, name),
    )


def create_called_entry(
    conn: PgConnection,
    org: UUID,
    queue: UUID,
    party: UUID,
    reservation: UUID | None,
    offering: UUID,
    workload: UUID,
    minute: int,
) -> UUID:
    return uuid_row(
        conn,
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,reservation_id,offering_id,status,"
        "arrived_at,admitted_at,called_at,expected_workload_classification_id) VALUES "
        "(%s,%s,%s,%s,%s,'called','2035-01-01T09:00Z','2035-01-01T09:05Z',"
        "make_timestamptz(2035,1,1,9,%s,0,'UTC'),%s) RETURNING id",
        (org, queue, party, reservation, offering, minute, workload),
    )
