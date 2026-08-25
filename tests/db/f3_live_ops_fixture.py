from dataclasses import dataclass
from uuid import UUID, uuid4

from f2_discovery_fixture import create_discovery_fixture
from f3_live_ops_seed import PgConnection, create_called_entry, create_workload, uuid_row


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


def create_live_ops_fixture(conn: PgConnection) -> LiveOpsFixture:
    base = create_discovery_fixture(conn)
    suffix = uuid4().hex
    party_b = uuid_row(
        conn,
        "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
        "VALUES (%s,'person','Subject B') RETURNING id",
        (base.organization_id,),
    )
    queue = uuid_row(
        conn,
        "INSERT INTO request_engine.service_queues "
        "(organization_id,location_id,offering_id,queue_key,display_name) "
        "VALUES (%s,%s,%s,%s,'Live Queue') RETURNING id",
        (base.organization_id, base.location_id, base.offering_id, f"queue-{suffix}"),
    )
    expected = create_workload(conn, base.organization_id, f"expected-{suffix}", "Expected")
    actual = create_workload(conn, base.organization_id, f"actual-{suffix}", "Actual")
    reservation = uuid_row(
        conn,
        "INSERT INTO request_engine.reservations "
        "(organization_id,offering_version_id,subject_party_id,during) "
        "VALUES (%s,%s,%s,tstzrange('2035-01-01T10:00Z','2035-01-01T10:30Z','[)')) "
        "RETURNING id",
        (base.organization_id, base.offering_version_id, base.party_id),
    )
    entry_a = create_called_entry(
        conn,
        base.organization_id,
        queue,
        base.party_id,
        reservation,
        base.offering_id,
        expected,
        10,
    )
    entry_b = create_called_entry(
        conn,
        base.organization_id,
        queue,
        party_b,
        None,
        base.offering_id,
        expected,
        20,
    )
    return LiveOpsFixture(
        base.organization_id,
        base.party_id,
        party_b,
        base.location_id,
        base.offering_version_id,
        base.resource_id,
        queue,
        expected,
        actual,
        reservation,
        entry_a,
        entry_b,
    )
