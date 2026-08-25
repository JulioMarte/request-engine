from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from f2_discovery_fixture import create_discovery_fixture
from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class LiveOpsFixture:
    organization_id: UUID
    party_a_id: UUID
    party_b_id: UUID
    location_id: UUID
    offering_version_id: UUID
    resource_id: UUID
    queue_id: UUID
    expected_workload_id: UUID
    actual_workload_id: UUID
    reservation_id: UUID
    entry_a_id: UUID
    entry_b_id: UUID


def _uuid(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_live_ops_fixture(conn: PgConnection) -> LiveOpsFixture:
    base = create_discovery_fixture(conn)
    suffix = uuid4().hex
    party_b = _uuid(
        conn,
        "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
        "VALUES (%s,'person','Subject B') RETURNING id",
        (base.organization_id,),
    )
    queue = _uuid(
        conn,
        "INSERT INTO request_engine.service_queues "
        "(organization_id,location_id,offering_id,queue_key,display_name) "
        "VALUES (%s,%s,%s,%s,'Live Queue') RETURNING id",
        (base.organization_id, base.location_id, base.offering_id, f"queue-{suffix}"),
    )
    expected = _workload(conn, base.organization_id, f"expected-{suffix}", "Expected")
    actual = _workload(conn, base.organization_id, f"actual-{suffix}", "Actual")
    reservation = _uuid(
        conn,
        "INSERT INTO request_engine.reservations "
        "(organization_id,offering_version_id,subject_party_id,during) "
        "VALUES (%s,%s,%s,tstzrange('2035-01-01T10:00Z','2035-01-01T10:30Z','[)')) "
        "RETURNING id",
        (base.organization_id, base.offering_version_id, base.party_id),
    )
    entry_a = _called_entry(
        conn, base.organization_id, queue, base.party_id,
        reservation, base.offering_id, expected, 10,
    )
    entry_b = _called_entry(
        conn, base.organization_id, queue, party_b, None, base.offering_id, expected, 20,
    )
    return LiveOpsFixture(
        base.organization_id, base.party_id, party_b, base.location_id,
        base.offering_version_id, base.resource_id, queue, expected, actual,
        reservation, entry_a, entry_b,
    )


def _workload(conn: PgConnection, org: UUID, key: str, name: str) -> UUID:
    return _uuid(
        conn,
        "INSERT INTO request_engine.operational_workload_classifications "
        "(organization_id,workload_key,display_name) VALUES (%s,%s,%s) RETURNING id",
        (org, key, name),
    )


def _called_entry(
    conn: PgConnection, org: UUID, queue: UUID, party: UUID,
    reservation: UUID | None, offering: UUID, workload: UUID, minute: int,
) -> UUID:
    return _uuid(
        conn,
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,reservation_id,offering_id,status,"
        "arrived_at,admitted_at,called_at,expected_workload_classification_id) VALUES "
        "(%s,%s,%s,%s,%s,'called','2035-01-01T09:00Z','2035-01-01T09:05Z',"
        "make_timestamptz(2035,1,1,9,%s,0,'UTC'),%s) RETURNING id",
        (org, queue, party, reservation, offering, minute, workload),
    )
